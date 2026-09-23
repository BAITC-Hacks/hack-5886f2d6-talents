"""Functional cluster explanations must reflect evidence and its limitations."""
from hackalem.export import cluster_hypothesis


def node(role, *, depth=2, seed=False, isolated=False):
    return {'role': role, 'depth': depth, 'is_seed': seed,
            'flags': {'isolated': isolated}}


def test_different_roles_give_different_function_hypotheses():
    collection = cluster_hypothesis([node('consolidator'), node('consolidator'), node('peripheral')])
    distribution = cluster_hypothesis([node('distributor'), node('peripheral')])
    transit = cluster_hypothesis([node('transit'), node('transit'), node('terminal')])
    assert 'сбора средств' in collection and 'консолидации 2 из 3' in collection
    assert 'распределения средств' in distribution and 'распределителей 1 из 2' in distribution
    assert 'транзитом средств' in transit and 'транзитных узлов 2 из 3' in transit
    assert len({collection, distribution, transit}) == 3


def test_mixed_collection_and_distribution_retains_both_counts():
    group = [node('coordinator'), node('consolidator'), node('distributor'), node('distributor')]
    text = cluster_hypothesis(group)
    assert 'сбор и перераспределение' in text
    assert 'консолидации 1' in text and 'распределителей 2 из 4' in text
    assert cluster_hypothesis(list(reversed(group))) == text


def test_isolated_seed_does_not_imply_function_or_safety():
    text = cluster_hypothesis([node('peripheral', depth=0, seed=True, isolated=True)])
    assert 'Назначение не определено' in text and 'узлов без наблюдаемых связей: 1' in text
    assert 'Seed: 1; входящие неполны' in text
    assert 'безопас' not in text.lower()


def test_boundary_only_cluster_does_not_imply_retained_funds():
    text = cluster_hypothesis([node('consolidator', depth=4), node('peripheral', depth=4)])
    assert 'Назначение не определено' in text
    assert 'depth=4: 2; исходящие неполны' in text
    assert 'конечные' not in text and 'сбор' not in text


def test_mixed_cluster_keeps_seed_and_boundary_limitations():
    text = cluster_hypothesis([node('coordinator'), node('peripheral', depth=0, seed=True),
                               node('consolidator', depth=4)])
    assert 'кандидатов в координирующие узлы 1 из 3' in text
    assert 'depth=4: 1; исходящие неполны' in text
    assert 'Seed: 1; входящие неполны' in text


def test_weak_roles_stay_undetermined_and_function_claims_are_cautious():
    unknown = cluster_hypothesis([node('peripheral'), node('peripheral')])
    assert 'Назначение не определено' in unknown
    for role in ('consolidator', 'transit', 'distributor', 'terminal', 'coordinator'):
        text = cluster_hypothesis([node(role)])
        assert text.startswith('Гипотеза:')
        assert 'Общий организатор не установлен.' in text
