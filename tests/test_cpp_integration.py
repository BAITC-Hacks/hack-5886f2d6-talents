"""Real C++ process checks; explicitly skipped when no engine is built."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
from jsonschema import validate

from hackalem.protocol import strict_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def engine():
    candidates = [Path(os.environ['HACKALEM_ENGINE'])] if 'HACKALEM_ENGINE' in os.environ else [
        ROOT/'engine/build/engine.exe', ROOT/'engine/build/Release/engine.exe', ROOT/'engine/build/engine']
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None:
        pytest.skip('Build C++ engine first or set HACKALEM_ENGINE')
    return executable.resolve()


def test_real_pipeline_with_config_and_unicode(engine, tmp_path):
    raw, out = tmp_path/'исходные данные', tmp_path/'итоговые данные'
    raw.mkdir()
    nodes = pd.DataFrame({'gid': [2, 10, 9223372036854775807], 'depth': [0, 4, 0], 'is_seed': [True, False, True]})
    edges = pd.DataFrame({'src': [2], 'dst': [10], 'sum_kzt': [5000.], 'n_tx': [1], 'depth': [4]})
    tx = pd.DataFrame({'src': [2], 'dst': [10], 'sum_kzt': [5000.], 'date': ['2026-07-01']})
    for name, frame in [('nodes', nodes), ('edges', edges), ('transactions', tx)]:
        frame.to_parquet(raw/f'{name}.parquet', index=False)
    config = tmp_path/'правила.json'
    config.write_text('{"priority_seed_saturation":7}', encoding='utf-8')
    proc = subprocess.run([sys.executable, str(ROOT/'pipeline.py'), '--core', str(engine), '--data', str(raw),
                           '--core-config', str(config), '--out', str(out)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    payload, result, graph = [strict_json(out/name) for name in ['input.json', 'result.json', 'graph.json']]
    validate(payload, strict_json(ROOT/'engine/schemas/input.schema.json'))
    validate(result, strict_json(ROOT/'engine/schemas/result.schema.json'))
    assert graph['meta']['is_demo'] is False
    assert graph['meta']['config']['priority_seed_saturation'] == 7
    assert graph['meta']['engine_meta'] == result['meta']
    assert graph['edges'][0]['id'] == '2:10'
    assert graph['top_nodes'] == result['top_nodes']
    by_gid = {n['gid']: n for n in graph['nodes']}
    for n in result['nodes']:
        assert 1 <= len(n['next_actions']) <= 3
        for key, value in n.items():
            assert by_gid[n['gid']][key] == value
    assert by_gid['9223372036854775807']['flags']['isolated']
    assert by_gid['10']['role'] not in ['terminal', 'transit']
    assert 'in_deg' in by_gid['2']
    assert strict_json(out/'run_manifest.json')['engine_config']['priority_seed_saturation'] == 7


def test_real_engine_numeric_tie_order(engine, tmp_path):
    # Use actual C++ output to ensure IDs of different lengths are sorted numerically.
    nodes = [{'gid': g, 'depth': 0, 'is_seed': True, 'cluster_id': i,
              'in_deg': 0, 'out_deg': 0, 'in_tx': 0, 'out_tx': 0, 'in_kzt': 0,
              'out_kzt': 0, 'pagerank': 1/3, 'pass_through': None}
             for i, g in enumerate(['10', '2', '-1'])]
    source, target = tmp_path/'input.json', tmp_path/'result.json'
    source.write_text(json.dumps({'schema_version': '1.0', 'nodes': nodes, 'edges': []}), encoding='utf-8')
    subprocess.run([str(engine), str(source), str(target)], check=True, capture_output=True, timeout=10)
    assert [n['gid'] for n in strict_json(target)['top_nodes']] == ['-1', '2', '10']
