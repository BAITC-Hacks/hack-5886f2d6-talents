"""Edge-based checks for every structural experiment scenario."""
from copy import deepcopy
import random

import pytest

from hackalem.resilience_reference import calculate_resilience, verify_resilience


def graph_input(gids, edges, *, first=None, scores=None):
    gids = [str(gid) for gid in gids]
    payload = {
        'nodes': [{'gid': gid, 'is_seed': True} for gid in gids],
        'edges': [{'src': str(src), 'dst': str(dst), 'sum_kzt': amount}
                  for src, dst, amount in edges],
    }
    results = {gid: {'gid': gid, 'priority_score': (scores or {}).get(
        gid, 1.0 if gid == str(first) else 0.0)} for gid in gids}
    return payload, results


def snapshot(strategy, k, removed, nodes, edges, components, isolated, largest,
             amount=0.0, total=0.0):
    return {
        'strategy': strategy, 'requested_k': k, 'removed_gids': removed,
        'remaining_nodes': nodes, 'remaining_edges': edges,
        'weak_components': components, 'isolated_nodes': isolated,
        'largest_component_nodes': largest,
        'largest_component_share_remaining': largest / nodes if nodes else 0.0,
        'removed_edge_sum_kzt': amount,
        'removed_edge_sum_share': amount / total if total else 0.0,
    }


@pytest.mark.parametrize('gids,edges,first,baseline,after', [
    pytest.param([1, 2, 3, 4, 5], [(1, 2, 10), (2, 3, 20), (3, 4, 30), (4, 5, 40)], 3,
                 (5, 4, 1, 0, 5), (4, 2, 2, 0, 2, 50, 100), id='chain-middle'),
    pytest.param([10, 2, 3, 4, 5], [(10, 2, 10), (3, 10, 20), (10, 4, 30), (5, 10, 40)], 10,
                 (5, 4, 1, 0, 5), (4, 0, 4, 4, 1, 100, 100), id='star-center'),
    pytest.param([1, 2, 3], [(1, 2, 10), (2, 3, 20), (3, 1, 30)], 2,
                 (3, 3, 1, 0, 3), (2, 1, 1, 0, 2, 30, 60), id='directed-cycle'),
    pytest.param([1, 2, 3, 4, 5], [(1, 2, 10), (2, 3, 20), (4, 5, 30)], 2,
                 (5, 3, 2, 0, 3), (4, 1, 3, 2, 2, 30, 60), id='two-components'),
    pytest.param([1, 2, 3], [(1, 2, 10)], 3,
                 (3, 1, 2, 1, 2), (2, 1, 1, 0, 2, 0, 10), id='isolated-seed'),
    pytest.param([1], [(1, 1, 25)], 1,
                 (1, 1, 1, 1, 1), (0, 0, 0, 0, 0, 25, 25), id='only-self-loop'),
    pytest.param([1, 2], [(1, 2, 10), (2, 1, 30)], 1,
                 (2, 2, 1, 0, 2), (1, 0, 1, 1, 1, 40, 40), id='reciprocal-edges'),
    pytest.param([], [], None,
                 (0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0), id='empty-graph'),
])
def test_baseline_and_first_removal(gids, edges, first, baseline, after):
    payload, results = graph_input(gids, edges, first=first)
    actual = calculate_resilience(payload, results)
    assert actual['baseline'] == snapshot('baseline', 0, [], *baseline)
    removed = [str(first)] if gids else []
    assert actual['scenarios'][0] == snapshot('priority', 1, removed, *after)
    assert [(row['strategy'], row['requested_k']) for row in actual['scenarios']] == [
        (strategy, k) for strategy in ('priority', 'volume') for k in (1, 3, 5, 10)]
    verify_resilience(actual, payload, results)


def test_all_eight_scenarios_have_independent_full_graph_denominators():
    payload, results = graph_input([1, 2, 3, 4, 5, 6],
                                  [(1, 2, 10), (2, 3, 20), (4, 5, 30)], first=2)
    expected = [
        snapshot('priority', 1, ['2'], 5, 1, 4, 3, 2, 30, 60),
        snapshot('priority', 3, ['2', '1', '3'], 3, 1, 2, 1, 2, 30, 60),
        snapshot('priority', 5, ['2', '1', '3', '4', '5'], 1, 0, 1, 1, 1, 60, 60),
        snapshot('priority', 10, ['2', '1', '3', '4', '5', '6'], 0, 0, 0, 0, 0, 60, 60),
        snapshot('volume', 1, ['4'], 5, 2, 3, 2, 3, 30, 60),
        snapshot('volume', 3, ['4', '5', '2'], 3, 0, 3, 3, 1, 60, 60),
        snapshot('volume', 5, ['4', '5', '2', '3', '1'], 1, 0, 1, 1, 1, 60, 60),
        snapshot('volume', 10, ['4', '5', '2', '3', '1', '6'], 0, 0, 0, 0, 0, 60, 60),
    ]
    assert calculate_resilience(payload, results)['scenarios'] == expected


def test_volume_fallback_uses_max_of_external_in_and_out_not_total_or_loops():
    # Node 1 has 120 total turnover but max(in, out)=60. Node 2 has max=100.
    payload, results = graph_input([1, 2, 3, 4, 5],
                                  [(3, 1, 60), (1, 4, 60), (2, 5, 100), (1, 1, 1000000)])
    for node in payload['nodes']:
        node['metrics'] = {'in_kzt': 1e20 if node['gid'] == '1' else 0}
    actual = calculate_resilience(payload, results)
    assert actual['scenarios'][4]['removed_gids'] == ['2']
    assert actual['scenarios'][5]['removed_gids'] == ['2', '5', '1']
    assert actual['baseline']['remaining_edges'] == 4


def test_volume_uses_contract_engine_features_and_original_edge_sums():
    # Removing a huge loop from an accumulated C++ sum may round external
    # turnover to zero. Ranking must use the serialized engine observations.
    payload, results = graph_input([1, 2], [(1, 1, 1e20), (1, 2, 6000)])
    results['1']['features'] = {'observed_in_kzt': 0, 'observed_out_kzt': 0}
    results['2']['features'] = {'observed_in_kzt': 6000, 'observed_out_kzt': 0}
    actual = calculate_resilience(payload, results)
    first = actual['scenarios'][4]
    assert first['removed_gids'] == ['2']
    assert first['remaining_edges'] == 1
    assert first['remaining_nodes'] == first['isolated_nodes'] == 1
    assert first['removed_edge_sum_kzt'] == 6000
    assert first['removed_edge_sum_share'] == 6000 / 1e20
    verify_resilience(actual, payload, results)


def test_volume_preserves_near_equal_engine_values_without_rounding():
    payload, results = graph_input([2, 10], [(2, 10, 0.3)])
    results['2']['features'] = {'observed_in_kzt': 0, 'observed_out_kzt': 0.3}
    results['10']['features'] = {'observed_in_kzt': 0.30000000000000004, 'observed_out_kzt': 0}
    assert calculate_resilience(payload, results)['scenarios'][4]['removed_gids'] == ['10']


def test_volume_uses_max_of_engine_observations_not_their_total():
    payload, results = graph_input([2, 10], [])
    results['2']['features'] = {'observed_in_kzt': 60, 'observed_out_kzt': 60}
    results['10']['features'] = {'observed_in_kzt': 0, 'observed_out_kzt': 100}
    assert calculate_resilience(payload, results)['scenarios'][4]['removed_gids'] == ['10']


@pytest.mark.parametrize('field', ['observed_in_kzt', 'observed_out_kzt'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True, '0', None])
def test_invalid_present_engine_observations_cannot_fall_back_to_edges(field, value):
    payload, results = graph_input([1], [(1, 1, 6000)])
    results['1']['features'] = {'observed_in_kzt': 0, 'observed_out_kzt': 0, field: value}
    with pytest.raises(ValueError, match=field):
        calculate_resilience(payload, results)


@pytest.mark.parametrize('field', ['observed_in_kzt', 'observed_out_kzt'])
def test_partial_engine_observations_cannot_fall_back_to_edges(field):
    payload, results = graph_input([1], [])
    results['1']['features'] = {field: 0}
    with pytest.raises(ValueError, match='observed_'):
        calculate_resilience(payload, results)


def test_priority_uses_unrounded_scores():
    payload, results = graph_input([2, 10], [], scores={'2': 0.1234567801, '10': 0.1234567802})
    assert calculate_resilience(payload, results)['scenarios'][0]['removed_gids'] == ['10']


@pytest.mark.parametrize('with_features', [False, True])
def test_both_rankings_break_ties_with_signed_int64_gids(with_features):
    gids = ['9223372036854775807', '10', '2', '-1', '-9223372036854775808']
    payload, results = graph_input(gids, [])
    if with_features:
        for row in results.values():
            row['features'] = {'observed_in_kzt': 0, 'observed_out_kzt': 0}
    expected = ['-9223372036854775808', '-1', '2', '10', '9223372036854775807']
    actual = calculate_resilience(payload, results)
    for offset in (0, 4):
        for index, k in enumerate((1, 3, 5, 10)):
            assert actual['scenarios'][offset + index]['removed_gids'] == expected[:k]


def test_loops_and_edge_between_two_removed_nodes_are_counted_once():
    payload, results = graph_input([1, 2, 3, 4],
                                  [(1, 2, 10), (2, 1, 20), (1, 1, 30), (4, 4, 40)])
    actual = calculate_resilience(payload, results)
    first = actual['scenarios'][0]
    assert first['removed_edge_sum_kzt'] == 60
    assert first['remaining_edges'] == 1
    assert first['isolated_nodes'] == 3
    third = actual['scenarios'][1]
    assert third == snapshot('priority', 3, ['1', '2', '3'], 1, 1, 1, 1, 1, 60, 100)
    assert actual['scenarios'][2]['removed_edge_sum_kzt'] == 100


def test_zero_total_amount_has_zero_removed_share():
    payload, results = graph_input([1, 2], [(1, 2, 0), (2, 1, 0), (2, 2, 0)])
    actual = calculate_resilience(payload, results)
    assert actual['baseline']['remaining_edges'] == 3
    for row in actual['scenarios']:
        assert row['removed_edge_sum_kzt'] == 0
        assert row['removed_edge_sum_share'] == 0


def test_shuffling_nodes_results_and_edges_preserves_every_value():
    payload, results = graph_input(range(1, 15),
                                  [(1, 2, 1e16), (1, 3, 1), (1, 4, 1), (5, 6, 1e16),
                                   (5, 7, 2), (4, 1, 11), (8, 8, 9), (13, 14, 0.1)])
    expected = calculate_resilience(payload, results)
    randomizer = random.Random(817)
    for _ in range(5):
        randomizer.shuffle(payload['nodes'])
        randomizer.shuffle(payload['edges'])
        items = list(results.items())
        randomizer.shuffle(items)
        assert calculate_resilience(payload, dict(items)) == expected


def test_largest_component_and_retained_edges_cannot_grow_with_k():
    payload, results = graph_input(range(1, 16),
                                  [(i, i + 1, i) for i in range(1, 12)] + [(13, 14, 8)])
    actual = calculate_resilience(payload, results)
    for rows in (actual['scenarios'][:4], actual['scenarios'][4:]):
        for field in ('largest_component_nodes', 'remaining_edges'):
            values = [actual['baseline'][field]] + [row[field] for row in rows]
            assert values == sorted(values, reverse=True)


SCENARIO_FIELDS = tuple(snapshot('baseline', 0, [], 0, 0, 0, 0, 0))


@pytest.mark.parametrize('field', SCENARIO_FIELDS)
@pytest.mark.parametrize('target', ['baseline'] + list(range(8)))
def test_verifier_checks_every_field_of_every_scenario(field, target):
    payload, results = graph_input(range(1, 13), [(i, i + 1, 10) for i in range(1, 12)])
    actual = calculate_resilience(payload, results)
    row = actual['baseline'] if target == 'baseline' else actual['scenarios'][target]
    value = row[field]
    row[field] = value + ['999'] if isinstance(value, list) else (
        'wrong' if isinstance(value, str) else value + 1)
    with pytest.raises(ValueError, match=field):
        verify_resilience(actual, payload, results)


@pytest.mark.parametrize('field', ['schema_version', 'connectivity', 'scope'])
def test_verifier_checks_header_fields(field):
    payload, results = graph_input([], [])
    actual = calculate_resilience(payload, results)
    actual[field] = 'wrong'
    with pytest.raises(ValueError, match=field):
        verify_resilience(actual, payload, results)


def test_verifier_checks_scenario_and_removed_gid_order():
    payload, results = graph_input([1, 2, 3, 4], [(1, 2, 10), (2, 3, 20)])
    expected = calculate_resilience(payload, results)
    wrong = deepcopy(expected)
    wrong['scenarios'].reverse()
    with pytest.raises(ValueError):
        verify_resilience(wrong, payload, results)
    wrong = deepcopy(expected)
    wrong['scenarios'][1]['removed_gids'].reverse()
    with pytest.raises(ValueError, match='removed_gids'):
        verify_resilience(wrong, payload, results)


def test_verifier_permits_only_small_floating_accumulation_error():
    payload, results = graph_input([1, 2, 3], [(1, 2, 0.1), (2, 3, 0.2)])
    actual = calculate_resilience(payload, results)
    actual['scenarios'][0]['removed_edge_sum_kzt'] += 1e-8
    actual['scenarios'][0]['removed_edge_sum_share'] += 1e-14
    verify_resilience(actual, payload, results)
    actual['scenarios'][0]['removed_edge_sum_share'] += 1e-8
    with pytest.raises(ValueError, match='removed_edge_sum_share'):
        verify_resilience(actual, payload, results)


def test_small_money_tampering_is_rejected_on_large_graph():
    payload, results = graph_input(range(2001), [(0, i, 1e8) for i in range(1, 2001)], first=0)
    actual = calculate_resilience(payload, results)
    assert actual['scenarios'][0]['removed_edge_sum_kzt'] == 2e11
    actual['scenarios'][0]['removed_edge_sum_kzt'] += 1
    with pytest.raises(ValueError, match='removed_edge_sum_kzt'):
        verify_resilience(actual, payload, results)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), True, '0'])
def test_verifier_rejects_invalid_numeric_values(value):
    payload, results = graph_input([1], [])
    actual = calculate_resilience(payload, results)
    actual['baseline']['removed_edge_sum_kzt'] = value
    with pytest.raises(ValueError, match='removed_edge_sum_kzt'):
        verify_resilience(actual, payload, results)
