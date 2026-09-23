import hashlib
import csv
import json
from pathlib import Path
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from demo_core import score
from hackalem.export import export_outputs
from hackalem.protocol import strict_json, validate_result, write_json
from verify_outputs import HASHED_FILES, PUBLIC_FILES, verify_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle(tmp_path):
    out = tmp_path/'public'/'data'
    out.mkdir(parents=True)
    payload = strict_json(ROOT/'examples/input.json')
    result = score(payload)
    graph = export_outputs(payload, validate_result(result, payload, demo=True), out,
                           result['engine'], True, engine_result=result)
    write_json(out/'input.json', payload)
    write_json(out/'result.json', result)
    write_json(out/'validation.json', payload['meta']['validation'])
    manifest = {'schema_version': '1.0', 'status': 'complete', 'demo': True,
                'source_sha256': {name: hashlib.sha256(b'fixture-only').hexdigest()
                                  for name in ('nodes.parquet', 'edges.parquet', 'transactions.parquet')},
                'counts': {k: len(graph[k]) for k in ('nodes', 'edges', 'clusters', 'top_nodes')},
                'clustering': payload['meta']['clustering'],
                'artifact_sha256': {name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in HASHED_FILES}}
    write_json(out/'run_manifest.json', manifest)
    return out


def rehash(out, name):
    manifest = strict_json(out/'run_manifest.json')
    manifest['artifact_sha256'][name] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    write_json(out/'run_manifest.json', manifest)


def test_bundle_requires_real_unless_explicit(bundle):
    with pytest.raises(ValueError, match='real C\\+\\+'):
        verify_bundle(bundle)
    result = verify_bundle(bundle, allow_demo=True)
    assert result['validated_artifact_count'] == 7
    assert result['counts']['nodes'] == 4
    assert result['source_hashes_checked'] is False


@pytest.mark.parametrize('mutation', ['missing_validation', 'missing_validation_hash', 'bad_hash',
                                     'validation_counts', 'lost_field', 'lost_null', 'missing_source_hash',
                                     'bad_csv', 'bad_cluster', 'path_escape'])
def test_corrupt_or_mixed_bundle_is_rejected(bundle, mutation):
    if mutation == 'missing_validation':
        (bundle/'validation.json').unlink()
    elif mutation in ('missing_validation_hash', 'path_escape', 'missing_source_hash'):
        manifest = strict_json(bundle/'run_manifest.json')
        if mutation == 'missing_validation_hash': manifest['artifact_sha256'].pop('validation.json')
        elif mutation == 'missing_source_hash': manifest['source_sha256'].pop('nodes.parquet')
        else: manifest['artifact_sha256']['../outside.json'] = '0'*64
        write_json(bundle/'run_manifest.json', manifest)
    elif mutation == 'bad_hash':
        with (bundle/'nodes_roles.csv').open('a', encoding='utf-8') as stream: stream.write('broken')
    elif mutation == 'validation_counts':
        validation = strict_json(bundle/'validation.json'); validation['n_nodes'] += 1
        write_json(bundle/'validation.json', validation); rehash(bundle, 'validation.json')
    elif mutation in ('lost_field', 'lost_null', 'bad_cluster'):
        graph = strict_json(bundle/'graph.json')
        if mutation == 'lost_field': graph['nodes'][0].pop('in_kzt')
        elif mutation == 'lost_null':
            next(n for n in graph['nodes'] if n['pass_through'] is None).pop('pass_through')
        else: graph['clusters'][0]['sum_kzt_internal'] += 10
        write_json(bundle/'graph.json', graph); rehash(bundle, 'graph.json')
    elif mutation == 'bad_csv':
        path = bundle/'top_nodes.csv'
        path.write_text(path.read_text(encoding='utf-8').replace('peripheral', 'terminal'), encoding='utf-8')
        rehash(bundle, 'top_nodes.csv')
    with pytest.raises(ValueError): verify_bundle(bundle, allow_demo=True)


def rewrite_csv_cell(out, filename, column, value):
    path = out/filename
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    rows[0][column] = value(rows[0][column]) if callable(value) else value
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    rehash(out, filename)


@pytest.mark.parametrize('hypothesis', ['', ' \t\n ', None, 17])
def test_cluster_hypothesis_requires_nonempty_text_even_with_valid_hashes(bundle, hypothesis):
    graph = strict_json(bundle/'graph.json')
    graph['clusters'][0]['hypothesis'] = hypothesis
    write_json(bundle/'graph.json', graph)
    rehash(bundle, 'graph.json')
    rewrite_csv_cell(bundle, 'clusters.csv', 'hypothesis', hypothesis)
    with pytest.raises(ValueError, match='hypothesis must be nonempty text'):
        verify_bundle(bundle, allow_demo=True)


@pytest.mark.parametrize('filename,column,suffix', [
    ('nodes_roles.csv', 'cluster_id', '.0'),
    ('nodes_roles.csv', 'cluster_id', '.0000000001'),
    ('clusters.csv', 'cluster_id', '.0000000000000000000001'),
    ('top_nodes.csv', 'rank', '.0'),
    ('top_nodes.csv', 'rank', '.0000000000000000000001'),
    ('clusters.csv', 'n_nodes', '.0000000001'),
    ('clusters.csv', 'n_seed', '.0000000000000000000001'),
])
def test_csv_integer_fields_reject_fractional_or_float_spelling(bundle, filename, column, suffix):
    # Rehashing models a writer bug, so consistency checks must catch this too.
    rewrite_csv_cell(bundle, filename, column, lambda value: value + suffix)
    with pytest.raises(ValueError):
        verify_bundle(bundle, allow_demo=True)


def test_exact_downloads_over_http(bundle):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(bundle.parent)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = verify_bundle(bundle, allow_demo=True, base_url=f'http://127.0.0.1:{server.server_port}/data')
        assert len(report['http_urls_checked']) == len(PUBLIC_FILES)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize('mutation', ['lost', 'changed', 'reordered', 'invented'])
def test_next_actions_must_match_engine_even_with_valid_hashes(bundle, mutation):
    payload = strict_json(bundle/'input.json')
    result = strict_json(bundle/'result.json')
    if mutation != 'invented':
        result['nodes'][0]['next_actions'] = [
            'Запросить входящие вне выборки.', 'Сопоставить даты переводов.']
        write_json(bundle/'result.json', result)
        rehash(bundle, 'result.json')
    graph = export_outputs(payload, validate_result(result, payload, demo=True), bundle,
                           result['engine'], True, engine_result=result)
    rehash(bundle, 'graph.json')
    verify_bundle(bundle, allow_demo=True)
    node = next(n for n in graph['nodes'] if n['gid'] == result['nodes'][0]['gid'])
    if mutation == 'lost':
        node.pop('next_actions')
    elif mutation == 'changed':
        node['next_actions'][0] = 'Другой текст.'
    elif mutation == 'reordered':
        node['next_actions'].reverse()
    else:
        node['next_actions'] = ['Действие, которого нет в результате ядра.']
    write_json(bundle/'graph.json', graph)
    rehash(bundle, 'graph.json')
    with pytest.raises(ValueError, match='next_actions'):
        verify_bundle(bundle, allow_demo=True)


def add_resilience(out):
    from hackalem.resilience_reference import calculate_resilience
    payload, result = [strict_json(out/name) for name in ('input.json', 'result.json')]
    result.setdefault('meta', {})['resilience'] = calculate_resilience(
        payload, {n['gid']: n for n in result['nodes']})
    write_json(out/'result.json', result)
    graph = export_outputs(payload, validate_result(result, payload, demo=True), out,
                           result['engine'], True, engine_result=result)
    for name in ('result.json', 'graph.json'):
        rehash(out, name)
    return graph


@pytest.mark.parametrize('location', ['meta', 'engine_meta'])
@pytest.mark.parametrize('mutation', ['lost', 'changed', 'reordered', 'invented', 'null', 'bool_count'])
def test_resilience_copies_must_match_result_even_with_valid_hashes(bundle, location, mutation):
    graph = add_resilience(bundle)
    assert verify_bundle(bundle, allow_demo=True)['resilience_scenarios_checked'] == 8
    if mutation == 'invented':
        result = strict_json(bundle/'result.json')
        result['meta'].pop('resilience')
        write_json(bundle/'result.json', result)
        rehash(bundle, 'result.json')
    else:
        target = graph['meta'] if location == 'meta' else graph['meta']['engine_meta']
        # Break the shared in-memory reference before testing one copy at a time.
        target['resilience'] = json.loads(json.dumps(target['resilience']))
        experiment = target['resilience']
        if mutation == 'lost': target.pop('resilience')
        elif mutation == 'changed': experiment['scenarios'][0]['removed_edge_sum_kzt'] += 1
        elif mutation == 'reordered': experiment['scenarios'].reverse()
        elif mutation == 'null': target['resilience'] = None
        elif mutation == 'bool_count': experiment['baseline']['isolated_nodes'] = True
        write_json(bundle/'graph.json', graph)
        rehash(bundle, 'graph.json')
    with pytest.raises(ValueError, match='resilience'):
        verify_bundle(bundle, allow_demo=True)


@pytest.mark.parametrize('field', ['weak_components', 'removed_edge_sum_kzt',
                                  'largest_component_share_remaining', 'removed_edge_sum_share'])
def test_networkx_catches_wrong_calculations_in_all_copies(bundle, field):
    add_resilience(bundle)
    result = strict_json(bundle/'result.json')
    scenario = result['meta']['resilience']['scenarios'][0]
    scenario[field] = (1 if scenario[field] != 1 else 2) if field == 'weak_components' else (0 if scenario[field] else 1)
    payload = strict_json(bundle/'input.json')
    export_outputs(payload, validate_result(result, payload, demo=True), bundle,
                   result['engine'], True, engine_result=result)
    write_json(bundle/'result.json', result)
    for name in ('graph.json', 'result.json'):
        rehash(bundle, name)
    with pytest.raises(ValueError, match='resilience'):
        verify_bundle(bundle, allow_demo=True)
