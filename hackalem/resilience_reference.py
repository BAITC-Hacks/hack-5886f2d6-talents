"""Independent NetworkX oracle for the optional structural experiment.

This module verifies engine output; it does not provide production metadata.
Retained edges, connectivity and removed sums come from the original input
edges. Volume ordering uses the engine's observed turnover, as the contract
requires, without rounding those values again.
"""
from __future__ import annotations

import math

import networkx as nx


REQUESTED_K = (1, 3, 5, 10)


def calculate_resilience(payload, results):
    """Reproduce baseline and all eight scenarios from validated input/results.

    ``results`` is a mapping from gid to validated, unrounded engine node rows.
    A directed graph supplies weak connectivity; the original edge list supplies
    edge counts and amounts, preserving loops and both reciprocal directions.
    Volume ranking uses ``features.observed_in_kzt`` / ``observed_out_kzt`` from
    production engine output. Demo rows and fixtures with neither field fall
    back to external turnover computed from input edges; a partial pair is an
    error. This fallback is not the production engine's ranking source.
    """
    gids = [node['gid'] for node in payload['nodes']]
    edges = [(edge['src'], edge['dst'], float(edge['sum_kzt']))
             for edge in payload['edges']]
    graph = nx.DiGraph()
    graph.add_nodes_from(gids)
    graph.add_edges_from((src, dst) for src, dst, _ in edges)

    incoming = {gid: [] for gid in gids}
    outgoing = {gid: [] for gid in gids}
    for src, dst, amount in edges:
        if src != dst:
            outgoing[src].append(amount)
            incoming[dst].append(amount)
    volumes = {}
    volume_fields = ('observed_in_kzt', 'observed_out_kzt')
    for gid in gids:
        features = results[gid].get('features', {})
        if not isinstance(features, dict):
            raise ValueError(f'{gid}: features must be an object')
        if any(field in features for field in volume_fields):
            for field in volume_fields:
                value = features.get(field)
                if (type(value) not in (int, float)
                        or not math.isfinite(value) or value < 0):
                    raise ValueError(f'{gid}: features.{field} must be finite and nonnegative')
            volumes[gid] = max(features[field] for field in volume_fields)
        else:
            volumes[gid] = max(math.fsum(incoming[gid]), math.fsum(outgoing[gid]))
    total_amount = math.fsum(amount for _, _, amount in edges)

    def scenario(strategy, requested_k, removed_gids):
        removed = set(removed_gids)
        retained = [gid for gid in gids if gid not in removed]
        remaining = graph.subgraph(retained)
        component_sizes = [len(component)
                           for component in nx.weakly_connected_components(remaining)]
        largest = max(component_sizes, default=0)
        external_neighbors = set()
        remaining_edges = 0
        removed_amounts = []
        for src, dst, amount in edges:
            if src in removed or dst in removed:
                removed_amounts.append(amount)
            else:
                remaining_edges += 1
                if src != dst:
                    external_neighbors.update((src, dst))
        removed_amount = math.fsum(removed_amounts)
        return {
            'strategy': strategy,
            'requested_k': requested_k,
            'removed_gids': list(removed_gids),
            'remaining_nodes': len(retained),
            'remaining_edges': remaining_edges,
            'weak_components': len(component_sizes),
            'isolated_nodes': len(retained) - len(external_neighbors),
            'largest_component_nodes': largest,
            'largest_component_share_remaining': largest / len(retained) if retained else 0.0,
            'removed_edge_sum_kzt': removed_amount,
            'removed_edge_sum_share': min(1.0, max(0.0, removed_amount / total_amount))
                                      if total_amount else 0.0,
        }

    priority = sorted(gids, key=lambda gid: (-results[gid]['priority_score'], int(gid)))
    volume = sorted(gids, key=lambda gid: (-volumes[gid], int(gid)))
    return {
        'schema_version': '1.0',
        'connectivity': 'weak',
        'scope': 'observed_graph',
        'baseline': scenario('baseline', 0, []),
        'scenarios': [scenario(strategy, k, ranking[:k])
                      for strategy, ranking in (('priority', priority), ('volume', volume))
                      for k in REQUESTED_K],
    }


def verify_resilience(resilience, payload, results):
    """Raise ValueError when any reported field differs from the edge-based oracle.

    Integer counts, strings and ordered lists must agree exactly. ``math.fsum``
    makes reference sums independent of edge order. Floating-point engine sums
    may accumulate in another order: allow 1e-12 relative error and 1e-6 KZT
    absolute error for money, or 1e-12 absolute error for dimensionless shares.
    Input/result validation, including score validity, is performed by callers.
    """
    expected = calculate_resilience(payload, results)

    def compare(actual, wanted, path):
        if isinstance(wanted, dict):
            if not isinstance(actual, dict):
                raise ValueError(f'{path}: expected an object')
            if actual.keys() != wanted.keys():
                raise ValueError(f'{path}: fields differ from the resilience contract')
            for key, value in wanted.items():
                compare(actual[key], value, f'{path}.{key}')
        elif isinstance(wanted, list):
            if not isinstance(actual, list) or len(actual) != len(wanted):
                raise ValueError(f'{path}: expected an array of length {len(wanted)}')
            for index, value in enumerate(wanted):
                compare(actual[index], value, f'{path}[{index}]')
        elif isinstance(wanted, float):
            absolute_tolerance = 1e-6 if path.endswith('.removed_edge_sum_kzt') else 1e-12
            if (type(actual) not in (int, float)
                    or not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=absolute_tolerance)):
                raise ValueError(f'{path}: got {actual!r}, expected {wanted!r} from resilience reference')
        elif type(actual) is not type(wanted) or actual != wanted:
            raise ValueError(f'{path}: got {actual!r}, expected {wanted!r} from resilience reference')

    compare(resilience, expected, 'resilience')
