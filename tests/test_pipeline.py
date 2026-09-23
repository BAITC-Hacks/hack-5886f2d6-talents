import copy
import json
from pathlib import Path
import subprocess
import sys

import networkx as nx
import pandas as pd
import pytest

from demo_core import score
from hackalem.data import DataError, basic_features, build_graph, cluster_graph, sanity_check
from hackalem.export import CSV_COLUMNS, export_outputs
from hackalem.protocol import make_input, strict_json, validate_result, write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    nodes = pd.DataFrame({'gid': [100000000000000001, 100000000000000002, 100000000000000003, 100000000000000004],
                          'depth': [0, 1, 4, 0], 'is_seed': [True, False, False, True]})
    a, b, c, _ = nodes.gid
    edges = pd.DataFrame({'src': [a, b, b], 'dst': [b, a, c], 'sum_kzt': [10000., 6000., 5000.],
                         'n_tx': [2, 1, 1], 'depth': [1, 2, 4]})
    tx = pd.DataFrame({'src': [a, a, b, b], 'dst': [b, b, a, c], 'sum_kzt': [5000., 5000., 6000., 5000.],
                      'date': ['2026-07-01']*4})
    return edges, nodes, tx


def payload_for(data):
    edges, nodes, tx = data
    report = sanity_check(edges, nodes, tx)
    G = build_graph(edges, nodes)
    df = basic_features(G, nodes)
    mapping, meta = cluster_graph(G)
    df['cluster_id'] = df.gid.map(mapping)
    df['neighbor_clusters'] = df.gid.map(lambda g: len({mapping[v] for v in set(G.predecessors(g)) | set(G.successors(g))}))
    return make_input(G, df, meta, report)


def test_isolate_precision_and_flags(data):
    payload = payload_for(data)
    nodes = {n['gid']: n for n in payload['nodes']}
    assert len(nodes) == 4
    assert all(type(gid) is str and len(gid) == 18 for gid in nodes)
    isolated = nodes['100000000000000004']
    assert isolated['metrics']['pagerank'] > 0
    assert isolated['metrics']['in_deg'] == isolated['metrics']['out_deg'] == 0
    assert isolated['metrics']['pass_through'] is None
    assert isolated['flags']['isolated']
    assert nodes['100000000000000003']['flags']['truncated_by_depth']
    assert not nodes['100000000000000001']['flags']['pass_through_reliable']
    assert sum(n['metrics']['pagerank'] for n in nodes.values()) == pytest.approx(1)
    assert payload['meta']['validation']['identical_transaction_rows'] == 1


@pytest.mark.parametrize('mutation,match', [
    ('amount', 'amount mismatch'), ('count', 'count mismatch'), ('duplicate_node', 'duplicate gid'),
    ('duplicate_edge', 'duplicate directed pair'), ('unknown', 'unknown endpoint'),
    ('float_gid', 'not floats'), ('null_gid', 'missing identifier'), ('negative', 'positive'),
    ('infinity', 'finite'), ('seed_string', 'boolean'), ('fractional_count', 'invalid integer'),
    ('missing_pair', 'pairs differ'), ('missing_date', 'missing date'),
])
def test_bad_data_fails(data, mutation, match):
    e, n, t = data
    if mutation == 'amount': e.loc[0, 'sum_kzt'] += 10
    if mutation == 'count': e.loc[0, 'n_tx'] += 1
    if mutation == 'duplicate_node': n.loc[1, 'gid'] = n.loc[0, 'gid']
    if mutation == 'duplicate_edge': e.loc[1, ['src', 'dst']] = e.loc[0, ['src', 'dst']].values
    if mutation == 'unknown': e.loc[0, 'src'] = 999
    if mutation == 'float_gid': n['gid'] = n.gid.astype(float)
    if mutation == 'null_gid': n['gid'] = n.gid.astype('Int64'); n.loc[0, 'gid'] = pd.NA
    if mutation == 'negative': t.loc[0, 'sum_kzt'] = -1
    if mutation == 'infinity': e.loc[0, 'sum_kzt'] = float('inf')
    if mutation == 'seed_string': n['is_seed'] = n.is_seed.astype(str)
    if mutation == 'fractional_count': e['n_tx'] = e.n_tx.astype(float); e.loc[0, 'n_tx'] = 1.5
    if mutation == 'missing_pair': t = t.iloc[:-1].copy()
    if mutation == 'missing_date': t.loc[0, 'date'] = None
    with pytest.raises((DataError, ValueError), match=match):
        sanity_check(e, n, t)


def test_absolute_amount_tolerance(data):
    e, n, t = data
    e.loc[0, 'sum_kzt'] += .005
    assert sanity_check(e, n, t)['ok']


def test_projection_sums_reverse_and_ignores_loops(monkeypatch):
    G = nx.DiGraph()
    G.add_nodes_from(['a', 'b', 'c', 'z'])
    G.add_edge('a', 'b', sum_kzt=10)
    G.add_edge('b', 'a', sum_kzt=20)
    G.add_edge('c', 'c', sum_kzt=1000)
    original = nx.community.louvain_communities
    def check(U, **kwargs):
        assert U['a']['b']['weight'] == 30
        assert nx.number_of_selfloops(U) == 0
        assert kwargs['seed'] == 42
        return original(U, **kwargs)
    monkeypatch.setattr(nx.community, 'louvain_communities', check)
    mapping, _ = cluster_graph(G)
    assert mapping['a'] == mapping['b']
    assert len({mapping['a'], mapping['c'], mapping['z']}) == 3


def test_all_isolates_and_shuffle(data):
    e, n, t = data
    first = payload_for((e.copy(), n.copy(), t.copy()))
    second = payload_for((e.sample(frac=1, random_state=3), n.sample(frac=1, random_state=4), t.sample(frac=1, random_state=5)))
    assert first == second
    G = nx.DiGraph()
    G.add_nodes_from(['a', 'b'])
    mapping, meta = cluster_graph(G)
    assert mapping == {'a': 0, 'b': 1}
    assert meta['modularity'] == 0


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'extra', 'float_gid', 'bad_role', 'nan', 'range', 'bool_score', 'blank', 'long', 'boundary_terminal', 'no_why', 'version'])
def test_invalid_core_result(data, mutation):
    payload = payload_for(data)
    result = score(payload)
    if mutation == 'missing': result['nodes'].pop()
    if mutation == 'duplicate': result['nodes'].append(result['nodes'][0])
    if mutation == 'extra': result['nodes'][0]['gid'] = 'unknown'
    if mutation == 'float_gid': result['nodes'][0]['gid'] = 100000000000000001
    if mutation == 'bad_role': result['nodes'][0]['role'] = 'criminal'
    if mutation == 'nan': result['nodes'][0]['role_score'] = float('nan')
    if mutation == 'range': result['nodes'][0]['priority_score'] = 1.1
    if mutation == 'bool_score': result['nodes'][0]['role_score'] = True
    if mutation == 'blank': result['nodes'][0]['evidence'] = ' '
    if mutation == 'long': result['nodes'][0]['evidence'] = 'a'*201
    if mutation == 'boundary_terminal': result['nodes'][2]['role'] = 'terminal'
    if mutation == 'no_why': result['nodes'][0].pop('why')
    if mutation == 'version': result['schema_version'] = '2.0'
    with pytest.raises(ValueError): validate_result(result, payload)


def test_export_consistency(data, tmp_path):
    payload = payload_for(data)
    result = score(payload)
    graph = export_outputs(payload, validate_result(result, payload), tmp_path, result['engine'], True)
    assert len(graph['nodes']) == 4
    assert sum(c['n_nodes'] for c in graph['clusters']) == 4
    assert sum(c['n_seed'] for c in graph['clusters']) == 2
    for name, columns in CSV_COLUMNS.items():
        assert list(pd.read_csv(tmp_path/name).columns) == columns
    assert graph['top_nodes'] == sorted(graph['top_nodes'], key=lambda n: (-n['priority_score'], n['gid']))
    by_gid = {n['gid']: n for n in graph['nodes']}
    expected = sum(e['sum_kzt'] for e in graph['edges'] if by_gid[e['src']]['cluster_id'] == by_gid[e['dst']]['cluster_id'])
    assert sum(c['sum_kzt_internal'] for c in graph['clusters']) == expected
    assert 'NaN' not in (tmp_path/'graph.json').read_text(encoding='utf-8')


def test_strict_json(tmp_path):
    for text in ['{"a":NaN}', '{"a":1,"a":2}', '{"extra":1e309}']:
        (tmp_path/'bad.json').write_text(text)
        with pytest.raises(ValueError): strict_json(tmp_path/'bad.json')


def test_one_command_and_prepare_only(data, tmp_path):
    raw, out = tmp_path/'raw data', tmp_path/'results with spaces'
    raw.mkdir()
    for name, frame in zip(['edges', 'nodes', 'transactions'], data):
        frame.to_parquet(raw/f'{name}.parquet', index=False)
    command = [sys.executable, str(ROOT/'pipeline.py'), '--data', str(raw), '--out', str(out)]
    proc = subprocess.run([*command, '--demo'], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert strict_json(out/'run_manifest.json')['counts']['nodes'] == 4
    assert len(pd.read_csv(out/'nodes_roles.csv', dtype={'gid': str})) == 4
    proc = subprocess.run([*command, '--prepare-only'], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    # Bad input cannot overwrite a previous successful graph.
    previous = (out/'graph.json').read_bytes()
    e = data[0].copy(); e.loc[0, 'n_tx'] += 1
    e.to_parquet(raw/'edges.parquet', index=False)
    proc = subprocess.run([*command, '--demo'], capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert (out/'graph.json').read_bytes() == previous


def test_whole_run_timeout(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT/'pipeline.py'), '--demo', '--timeout', '.01', '--out', str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 124


def test_examples_are_valid():
    payload = strict_json(ROOT/'examples/input.json')
    validate_result(strict_json(ROOT/'examples/result.json'), payload)


@pytest.mark.parametrize('mode', ['nonzero', 'missing', 'bad_coverage', 'success'])
def test_external_core_boundary(data, tmp_path, monkeypatch, mode):
    """Exercise the real --core worker branch without claiming to run Arthur's code."""
    import pipeline
    from types import SimpleNamespace
    import time
    raw, out = tmp_path/'raw', tmp_path/'out'
    raw.mkdir(); out.mkdir()
    for name, frame in zip(['edges', 'nodes', 'transactions'], data):
        frame.to_parquet(raw/f'{name}.parquet', index=False)
    (out/'result.json').write_text('{"stale":true}')
    (out/'graph.json').write_text('previous successful graph')

    class FakeCore:
        def __init__(self, command, **kwargs):
            assert kwargs['shell'] is False
            assert command[1] == '--input' and command[3] == '--output'
            input_path, output_path = Path(command[2]), Path(command[4])
            assert input_path.is_absolute() and output_path.is_absolute()
            assert output_path.parent != out and not output_path.exists()
            if mode in ('success', 'bad_coverage'):
                result = score(strict_json(input_path))
                if mode == 'bad_coverage': result['nodes'].pop()
                write_json(output_path, result)

        def wait(self, timeout=None):
            return 7 if mode == 'nonzero' else 0

    monkeypatch.setattr(pipeline.subprocess, 'Popen', FakeCore)
    args = SimpleNamespace(out=out, data=raw, seed=42, resolution=1.0, prepare_only=False,
                           demo=False, core=tmp_path/'core.exe', deadline=time.time()+30,
                           core_timeout=20, top=20)
    if mode == 'success':
        pipeline.worker(args)
        assert len(strict_json(out/'graph.json')['nodes']) == 4
    else:
        with pytest.raises((RuntimeError, ValueError)):
            pipeline.worker(args)
        assert (out/'graph.json').read_text() == 'previous successful graph'
        assert strict_json(out/'result.json') == {'stale': True}
