"""Validate the optional C++ structural experiment without changing its values."""
from __future__ import annotations

import math


def validate_resilience(value, payload):
    """Check the v1 contract, including JSON types, ordering and node coverage."""
    def require(condition, message):
        if not condition:
            raise ValueError(f'resilience: {message}')

    require(isinstance(value, dict), 'must be an object')
    for key, expected in (('schema_version', '1.0'), ('connectivity', 'weak'),
                          ('scope', 'observed_graph')):
        require(value.get(key) == expected, f'{key} must be {expected}')
    scenarios = value.get('scenarios')
    require(isinstance(scenarios, list) and len(scenarios) == 8,
            'scenarios must contain all eight priority/volume experiments')
    expected_order = [('baseline', 0)] + [(strategy, k)
        for strategy in ('priority', 'volume') for k in (1, 3, 5, 10)]
    gids = {node['gid'] for node in payload['nodes']}
    for scenario, (strategy, k) in zip([value.get('baseline'), *scenarios], expected_order):
        label = f'{strategy}/{k}'
        require(isinstance(scenario, dict), f'{label} must be an object')
        require(scenario.get('strategy') == strategy, f'{label}: unexpected strategy/order')
        require(type(scenario.get('requested_k')) is int and scenario['requested_k'] == k,
                f'{label}: unexpected requested_k')
        removed = scenario.get('removed_gids')
        require(isinstance(removed, list) and all(isinstance(g, str) for g in removed),
                f'{label}: removed_gids must be an array of strings')
        require(len(removed) == len(set(removed)) == min(k, len(gids))
                and set(removed) <= gids, f'{label}: invalid removed_gids coverage')
        for key in ('remaining_nodes', 'remaining_edges', 'weak_components',
                    'isolated_nodes', 'largest_component_nodes'):
            require(type(scenario.get(key)) is int and scenario[key] >= 0,
                    f'{label}: {key} must be a nonnegative integer')
        for key in ('largest_component_share_remaining', 'removed_edge_sum_kzt',
                    'removed_edge_sum_share'):
            number = scenario.get(key)
            require(type(number) in (int, float) and math.isfinite(number) and number >= 0,
                    f'{label}: {key} must be a finite nonnegative number')
            if key != 'removed_edge_sum_kzt':
                require(number <= 1, f'{label}: {key} must be in [0,1]')
        remaining = scenario['remaining_nodes']
        require(remaining == len(gids) - len(removed), f'{label}: remaining_nodes differs')
        require(scenario['remaining_edges'] <= len(payload['edges']),
                f'{label}: remaining_edges exceeds input')
        for key in ('weak_components', 'isolated_nodes', 'largest_component_nodes'):
            require(scenario[key] <= remaining, f'{label}: {key} exceeds remaining_nodes')
        if remaining:
            require(scenario['weak_components'] > 0 and scenario['largest_component_nodes'] > 0,
                    f'{label}: nonempty graph must contain a component')
        else:
            require(scenario['remaining_edges'] == 0, f'{label}: empty graph contains edges')
        if strategy == 'baseline':
            require(scenario['remaining_edges'] == len(payload['edges'])
                    and scenario['removed_edge_sum_kzt'] == 0
                    and scenario['removed_edge_sum_share'] == 0,
                    'baseline must retain every edge and remove no turnover')
