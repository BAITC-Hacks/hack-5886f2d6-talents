"""Versioned JSON contract and strict validation of the external core output."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROLES = ['consolidator', 'transit', 'distributor', 'terminal', 'coordinator', 'peripheral']
METRICS = ['in_deg', 'out_deg', 'in_kzt', 'out_kzt', 'in_tx', 'out_tx', 'pagerank',
           'pass_through', 'seed_in_neighbors', 'neighbor_clusters', 'turnover_kzt']
FLAGS = ['isolated', 'boundary_depth', 'truncated_by_depth', 'seed_inflow_incomplete', 'pass_through_reliable']
LIMITATIONS = [
    'Роли и кластеры — гипотезы для проверки, не выводы о виновности.',
    'Depth=4 — граница наблюдений; отсутствие исходящих не доказывает конечное получение.',
    'Входящие seed неполны; отношения сумм не отражают полный баланс.',
    'Видны только внутрибанковские переводы за июль 2026 от 5000 KZT.',
    'Связь с seed и членство в сообществе сами по себе не доказывают причастность.',
]


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def strict_json(path: Path):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError(f'duplicate JSON key: {k}')
            result[k] = v
        return result

    def nonfinite(value):
        raise ValueError(f'nonfinite JSON value: {value}')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f'nonfinite JSON value: {value}')
        return number

    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=nonfinite, parse_float=finite_float)


def make_input(G, features, clustering, validation):
    rows = []
    for r in features.to_dict('records'):
        metrics = {k: r[k] for k in METRICS}
        for k, v in metrics.items():
            if isinstance(v, float) and not math.isfinite(v):
                if k != 'pass_through' or not math.isnan(v):
                    raise ValueError(f'nonfinite metric {k} for {r["gid"]}')
                metrics[k] = None
        rows.append({'gid': r['gid'], 'depth': r['depth'], 'is_seed': r['is_seed'],
                     'cluster_id': r['cluster_id'], **metrics,
                     'truncated_by_depth': bool(r['truncated_by_depth']), 'metrics': metrics,
                     'flags': {k: bool(r[k]) for k in FLAGS}})
    return {'schema_version': '1.0',
            'meta': {'limitations': LIMITATIONS, 'clustering': clustering, 'validation': validation},
            'nodes': rows,
            'edges': [{'src': u, 'dst': v, **a} for u, v, a in G.edges(data=True)]}


def validate_result(result, payload, *, demo=False):
    if not isinstance(result, dict) or result.get('schema_version') != '1.0':
        raise ValueError('result.schema_version must be 1.0')
    if demo:
        if result.get('engine') != 'python-demo-v1':
            raise ValueError('demo result.engine must be python-demo-v1')
    else:
        from jsonschema import Draft202012Validator
        schema = strict_json(Path(__file__).resolve().parents[1] / 'engine/schemas/result.schema.json')
        errors = list(Draft202012Validator(schema).iter_errors(result))
        if errors:
            raise ValueError(f'C++ result schema: {errors[0].message}')
        if not result['engine_version'].strip():
            raise ValueError('result.engine_version must be nonempty')
    if not isinstance(result.get('nodes'), list):
        raise ValueError('result.nodes must be an array')
    expected = {n['gid']: n for n in payload['nodes']}
    found = {}
    for n in result['nodes']:
        if not isinstance(n, dict):
            raise ValueError('each result node must be an object')
        gid = n.get('gid')
        if not isinstance(gid, str) or gid not in expected or gid in found:
            raise ValueError(f'unknown, non-string or duplicate result gid: {gid}')
        if n.get('role') not in ROLES:
            raise ValueError(f'{gid}: invalid role')
        for key in ('role_score', 'priority_score'):
            value = n.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'{gid}: {key} must be finite in [0,1]')
        for key in ('evidence', 'why'):
            value = n.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{gid}: {key} must be nonempty text')
        if len(n['evidence']) > 200:
            raise ValueError(f'{gid}: evidence exceeds 200 characters')
        if expected[gid]['flags']['truncated_by_depth'] and n['role'] == 'terminal':
            raise ValueError(f'{gid}: terminal role forbidden at truncated depth boundary')
        fields = ['gid', 'role', 'role_score', 'priority_score', 'evidence', 'why']
        if 'next_actions' in n:
            actions = n['next_actions']
            if (not isinstance(actions, list) or not 1 <= len(actions) <= 3
                    or any(not isinstance(a, str) or not a.strip() or len(a) > 200 for a in actions)
                    or len(set(actions)) != len(actions)):
                raise ValueError(f'{gid}: next_actions must contain 1-3 unique nonempty strings, at most 200 characters each')
            fields.append('next_actions')
        if not demo:
            if type(n['cluster_id']) is not int or n['cluster_id'] != expected[gid]['cluster_id']:
                raise ValueError(f'{gid}: result cluster_id differs from Python input')
            fields += ['cluster_id', 'features', 'role_candidates', 'priority_breakdown', 'warnings']
        found[gid] = {k: n[k] for k in fields}
    if set(found) != set(expected):
        raise ValueError(f'result missing {len(set(expected)-set(found))} nodes')
    if not demo:
        ranked = sorted(found.values(), key=lambda n: (-n['priority_score'], int(n['gid'])))[:20]
        expected_top = [{'rank': i+1, **{k: n[k] for k in ('gid', 'role', 'priority_score', 'why')}}
                        for i, n in enumerate(ranked)]
        if result['top_nodes'] != expected_top:
            raise ValueError('C++ top_nodes differs from full node scores or numeric gid ordering')
    return found
