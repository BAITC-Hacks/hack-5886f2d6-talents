"""Generate the three exact CSV schemas and the UI graph payload."""
import json
import math

import pandas as pd

from .protocol import write_json

CSV_COLUMNS = {
    'nodes_roles.csv': ['gid', 'role', 'role_score', 'cluster_id', 'priority_score', 'evidence'],
    'clusters.csv': ['cluster_id', 'n_nodes', 'n_seed', 'sum_kzt_internal', 'top_gids', 'hypothesis'],
    'top_nodes.csv': ['rank', 'gid', 'role', 'priority_score', 'why'],
}


def export_outputs(payload, results, out_dir, engine, demo, top_n=20):
    nodes = [{**n, **results[n['gid']]} for n in payload['nodes']]
    ranked = sorted(nodes, key=lambda n: (-n['priority_score'], n['gid']))
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
        if len(group) == 1 and group[0]['flags']['isolated']:
            hypothesis = 'Нет наблюдаемых связей; назначение не определено.'
        else:
            hypothesis = (f'Гипотеза: сообщество связанных переводов, seed={n_seed}; '
                          'проверить потоки лидеров. Общий организатор не установлен.')
        clusters.append({'cluster_id': cid, 'n_nodes': len(group), 'n_seed': n_seed,
                         'sum_kzt_internal': float(math.fsum(internal[cid])),
                         'top_gids': [n['gid'] for n in group[:5]], 'hypothesis': hypothesis})
    graph = {'schema_version': '1.0', 'meta': {**payload['meta'], 'engine': engine, 'demo': demo},
             'nodes': nodes, 'edges': payload['edges'], 'clusters': clusters, 'top_nodes': top}
    for name, rows in [('nodes_roles.csv', nodes), ('clusters.csv', clusters), ('top_nodes.csv', top)]:
        frame = pd.DataFrame(rows, columns=CSV_COLUMNS[name])
        if name == 'clusters.csv':
            frame['top_gids'] = frame.top_gids.map(lambda x: json.dumps(x, ensure_ascii=False))
        frame.to_csv(out_dir / name, index=False, encoding='utf-8', lineterminator='\n')
    write_json(out_dir / 'graph.json', graph)
    return graph
