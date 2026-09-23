"""Generate the three exact CSV schemas and the UI graph payload."""
import json
import math
from collections import Counter

import pandas as pd

from .protocol import write_json

CSV_COLUMNS = {
    'nodes_roles.csv': ['gid', 'role', 'role_score', 'cluster_id', 'priority_score', 'evidence'],
    'clusters.csv': ['cluster_id', 'n_nodes', 'n_seed', 'sum_kzt_internal', 'top_gids', 'hypothesis'],
    'top_nodes.csv': ['rank', 'gid', 'role', 'priority_score', 'why'],
}


def cluster_hypothesis(group):
    """Describe a possible function using only the members' calculated roles.

    Precedence: no observed edges, all boundary, consolidation + distribution,
    coordinator, consolidation, distribution, transit, terminal, undetermined.
    Counts describe primary role hypotheses, not confirmed activity or one owner.
    Boundary and seed caveats apply independently of the selected description.
    """
    size = len(group)
    roles = Counter(n['role'] for n in group)
    boundary = sum(n['depth'] == 4 for n in group)
    seeds = sum(n['is_seed'] for n in group)
    if all(n['flags']['isolated'] for n in group):
        description = f'Назначение не определено; узлов без наблюдаемых связей: {size}.'
    elif boundary == size:
        description = 'Назначение не определено: весь кластер на границе наблюдений.'
    elif roles['consolidator'] and roles['distributor']:
        description = (f'Гипотеза: сбор и перераспределение средств; '
                       f'точек консолидации {roles["consolidator"]}, '
                       f'распределителей {roles["distributor"]} из {size} узлов.')
    elif roles['coordinator']:
        description = (f'Гипотеза: связь нескольких ветвей сети; '
                       f'кандидатов в координирующие узлы {roles["coordinator"]} из {size}.')
    elif roles['consolidator']:
        description = (f'Гипотеза: фрагмент сбора средств; '
                       f'точек консолидации {roles["consolidator"]} из {size} узлов.')
    elif roles['distributor']:
        description = (f'Гипотеза: фрагмент распределения средств; '
                       f'распределителей {roles["distributor"]} из {size} узлов.')
    elif roles['transit']:
        description = (f'Гипотеза: фрагмент с транзитом средств; '
                       f'транзитных узлов {roles["transit"]} из {size}.')
    elif roles['terminal']:
        description = (f'Гипотеза: принимающая ветвь сети; '
                       f'кандидатов в конечные получатели {roles["terminal"]} из {size} узлов.')
    else:
        description = f'Назначение не определено: у {size} узлов нет выраженной роли; проверить лидеров.'
    caveats = []
    if boundary:
        caveats.append(f'Граничных узлов depth=4: {boundary}; исходящие неполны.')
    if seeds:
        caveats.append(f'Seed: {seeds}; входящие неполны.')
    caveats.append('Общий организатор не установлен.')
    return ' '.join([description, *caveats])


def export_outputs(payload, results, out_dir, engine, demo, top_n=20, engine_result=None):
    nodes = [{**n, **results[n['gid']]} for n in payload['nodes']]
    ranked = sorted(nodes, key=lambda n: (-n['priority_score'], int(n['gid'])))
    top = [{'rank': i+1, **{k: n[k] for k in ('gid', 'role', 'priority_score', 'why')}}
           for i, n in enumerate(ranked[:max(20, top_n)])]
    members = {}
    by_gid = {n['gid']: n for n in nodes}
    for n in ranked:
        members.setdefault(n['cluster_id'], []).append(n)
    internal = {cid: [] for cid in members}
    for edge in payload['edges']:
        cid = by_gid[edge['src']]['cluster_id']
        if cid == by_gid[edge['dst']]['cluster_id']:
            internal[cid].append(edge['sum_kzt'])
    clusters = []
    for cid, group in sorted(members.items()):
        n_seed = sum(n['is_seed'] for n in group)
        clusters.append({'cluster_id': cid, 'n_nodes': len(group), 'n_seed': n_seed,
                         'sum_kzt_internal': float(math.fsum(internal[cid])),
                         'top_gids': [n['gid'] for n in group[:5]],
                         'hypothesis': cluster_hypothesis(group)})
    engine_meta = engine_result.get('meta', {}) if engine_result else {}
    meta = {**engine_meta, **payload['meta'], 'engine': engine, 'demo': demo, 'is_demo': demo,
            'engine_meta': engine_meta}
    if engine_result and 'engine_version' in engine_result:
        meta['engine_version'] = engine_result['engine_version']
    graph = {'schema_version': '1.0', 'meta': meta,
             'nodes': nodes, 'edges': [{'id': e['src']+':'+e['dst'], **e} for e in payload['edges']],
             'clusters': clusters, 'top_nodes': top}
    for name, rows in [('nodes_roles.csv', nodes), ('clusters.csv', clusters), ('top_nodes.csv', top)]:
        frame = pd.DataFrame(rows, columns=CSV_COLUMNS[name])
        if name == 'clusters.csv':
            frame['top_gids'] = frame.top_gids.map(lambda x: json.dumps(x, ensure_ascii=False))
        frame.to_csv(out_dir / name, index=False, encoding='utf-8', lineterminator='\n')
    write_json(out_dir / 'graph.json', graph)
    return graph
