"""Regenerate tiny synthetic contract examples with an isolated seed and boundary node."""
from pathlib import Path

import pandas as pd

from demo_core import score
from hackalem.data import sanity_check, build_graph, basic_features, cluster_graph
from hackalem.export import export_outputs
from hackalem.protocol import make_input, write_json, validate_result


def main():
    out = Path(__file__).resolve().parent / 'examples'
    out.mkdir(exist_ok=True)
    nodes = pd.DataFrame([
        {'gid': '100000000000000001', 'depth': 0, 'is_seed': True},
        {'gid': '100000000000000002', 'depth': 1, 'is_seed': False},
        {'gid': '100000000000000003', 'depth': 4, 'is_seed': False},
        {'gid': '100000000000000004', 'depth': 0, 'is_seed': True},
    ])
    edges = pd.DataFrame([
        {'src': '100000000000000001', 'dst': '100000000000000002', 'sum_kzt': 10000., 'n_tx': 2, 'depth': 1},
        {'src': '100000000000000002', 'dst': '100000000000000003', 'sum_kzt': 9000., 'n_tx': 1, 'depth': 4},
    ])
    tx = pd.DataFrame([
        {'src': edges.iloc[0].src, 'dst': edges.iloc[0].dst, 'sum_kzt': 5000., 'date': '2026-07-01'},
        {'src': edges.iloc[0].src, 'dst': edges.iloc[0].dst, 'sum_kzt': 5000., 'date': '2026-07-02'},
        {'src': edges.iloc[1].src, 'dst': edges.iloc[1].dst, 'sum_kzt': 9000., 'date': '2026-07-03'},
    ])
    validation = sanity_check(edges, nodes, tx)
    G = build_graph(edges, nodes)
    features = basic_features(G, nodes)
    mapping, clustering = cluster_graph(G)
    features['cluster_id'] = features.gid.map(mapping)
    features['neighbor_clusters'] = features.gid.map(lambda gid: len({mapping[v] for v in set(G.predecessors(gid)) | set(G.successors(gid))}))
    payload = make_input(G, features, clustering, validation)
    payload['meta']['synthetic_example'] = True
    payload['meta']['note'] = 'Tiny protocol example, not a complete BFS extract or submission dataset.'
    result = score(payload)
    write_json(out/'input.json', payload)
    write_json(out/'result.json', result)
    export_outputs(payload, validate_result(result, payload), out, result['engine'], True)


if __name__ == '__main__':
    main()
