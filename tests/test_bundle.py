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
