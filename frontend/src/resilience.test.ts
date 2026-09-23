import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ResiliencePanel, { ResilienceComparison, resilienceCaveat } from './ResiliencePanel';
import { parseResilience, resilienceCounts, resilienceScenario, type Resilience, type Scenario } from './resilience';

const gids = ['100000000000000001', '100000000000000002', '100000000000000003', '100000000000000004', '100000000000000005'];
const nodeIds = new Set(gids);
function scenario(strategy: Scenario['strategy'], requested_k: number, removed_gids: string[], remaining_nodes: number,
  remaining_edges: number, weak_components: number, isolated_nodes: number, largest_component_nodes: number,
  largest_component_share_remaining: number, removed_edge_sum_kzt: number, removed_edge_sum_share: number): Scenario {
  return { strategy, requested_k, removed_gids, remaining_nodes, remaining_edges, weak_components, isolated_nodes,
    largest_component_nodes, largest_component_share_remaining, removed_edge_sum_kzt, removed_edge_sum_share };
}
// Prepared results for a five-client star. Different selections intentionally have different effects.
function star(): Resilience {
  const scenarios: Scenario[] = [];
  for (const strategy of ['priority', 'volume'] as const) for (const k of resilienceCounts) {
    if (k >= 5) scenarios.push(scenario(strategy, k, [...gids], 0, 0, 0, 0, 0, 0, 100, 1));
    else if (strategy === 'priority') scenarios.push(scenario(strategy, k, gids.slice(0, k), 5 - k, 0, 5 - k, 5 - k, 1, 1 / (5 - k), 100, 1));
    else scenarios.push(scenario(strategy, k, gids.slice(1, 1 + k), 5 - k, 4 - k, 1, 0, 5 - k, 1, k * 25, k / 4));
  }
  return { schema_version: '1.0', connectivity: 'weak', scope: 'observed_graph',
    baseline: scenario('baseline', 0, [], 5, 4, 1, 0, 5, 1, 0, 0), scenarios };
}
function empty(): Resilience {
  return { schema_version: '1.0', connectivity: 'weak', scope: 'observed_graph',
    baseline: scenario('baseline', 0, [], 0, 0, 0, 0, 0, 0, 0, 0),
    scenarios: (['priority', 'volume'] as const).flatMap(strategy => resilienceCounts.map(k => scenario(strategy, k, [], 0, 0, 0, 0, 0, 0, 0, 0))) };
}

test('preserves all eight prepared scenarios and their differing outcomes without changing source data', () => {
  const raw = star(), before = structuredClone(raw), data = parseResilience(raw, nodeIds, 4)!;
  assert.deepEqual(data, raw); assert.deepEqual(raw, before);
  for (const strategy of ['priority', 'volume'] as const) for (const k of resilienceCounts) {
    const selected = resilienceScenario(data, strategy, k);
    assert.deepEqual(selected, raw.scenarios.find(item => item.strategy === strategy && item.requested_k === k));
    const html = renderToStaticMarkup(createElement(ResilienceComparison, { baseline: data.baseline, scenario: selected }));
    assert.ok(html.includes(`${selected.largest_component_nodes} клиентов`));
    assert.ok(html.includes('среди оставшихся клиентов'));
  }
  assert.equal(resilienceScenario(data, 'priority', 1).largest_component_nodes, 1);
  assert.equal(resilienceScenario(data, 'volume', 1).largest_component_nodes, 4);
});

test('supports old bundles without the optional field but rejects an explicitly malformed field', () => {
  assert.equal(parseResilience(undefined, nodeIds, 4), undefined);
  for (const invalid of [null, false, [], 'none', 0, {}]) assert.throws(() => parseResilience(invalid, nodeIds, 4), /Неверный формат «Устойчивость наблюдаемой сети»/);
});

test('rejects missing combinations and duplicate strategy/count pairs', () => {
  const missing = star(); missing.scenarios.pop();
  assert.throws(() => parseResilience(missing, nodeIds, 4), /все 8 сочетаний/);
  const duplicate = star(); duplicate.scenarios[7] = { ...duplicate.scenarios[0] };
  assert.throws(() => parseResilience(duplicate, nodeIds, 4), /повторяется/);
  const invalidN = star(); invalidN.scenarios[0].requested_k = 2;
  assert.throws(() => parseResilience(invalidN, nodeIds, 4), /число исключённых/);
});

test('rejects non-finite, out-of-range and inconsistent prepared metrics rather than filling in zeros', () => {
  const fields: [keyof Scenario, unknown][] = [
    ['remaining_nodes', -1], ['remaining_edges', 1.5], ['weak_components', NaN], ['isolated_nodes', 99],
    ['largest_component_nodes', 10], ['largest_component_share_remaining', 1.1],
    ['removed_edge_sum_kzt', Infinity], ['removed_edge_sum_share', -0.01],
    ['remaining_nodes', undefined], ['largest_component_share_remaining', 0.5],
  ];
  for (const [key, value] of fields) {
    const raw = star(); Object.assign(raw.scenarios[0], { [key]: value });
    assert.throws(() => parseResilience(raw, nodeIds, 4), /Неверный формат/, key);
  }
  const baseline = star(); baseline.baseline.removed_edge_sum_kzt = 1;
  assert.throws(() => parseResilience(baseline, nodeIds, 4), /исходная модель/);
});

test('validates removed IDs as known unique strings and checks the actual removal count', () => {
  for (const removed of [[100000000000000001], ['missing'], [], [gids[0], gids[0]]]) {
    const raw = star(); Object.assign(raw.scenarios[0], { removed_gids: removed });
    assert.throws(() => parseResilience(raw, nodeIds, 4), /Неверный формат/);
  }
  const full = resilienceScenario(parseResilience(star(), nodeIds, 4)!, 'priority', 10);
  assert.equal(full.requested_k, 10); assert.equal(full.removed_gids.length, 5);
  assert.equal(full.remaining_nodes, 0); assert.equal(full.largest_component_share_remaining, 0);
});

test('accepts an empty source network and a self-loop client that is fully excluded', () => {
  const emptyData = parseResilience(empty(), new Set(), 0)!;
  assert.equal(resilienceScenario(emptyData, 'volume', 10).remaining_nodes, 0);
  const html = renderToStaticMarkup(createElement(ResiliencePanel, { resilience: emptyData, onSelectClient: () => {}, onShowOriginal: () => {} }));
  assert.ok(html.includes('В этой модели нет исключённых клиентов.'));
  assert.ok(html.includes('Фактически исключено: 0.')); assert.ok(!html.includes('NaN'));
  const selfLoop = empty();
  selfLoop.baseline = scenario('baseline', 0, [], 1, 1, 1, 1, 1, 1, 0, 0);
  selfLoop.scenarios = selfLoop.scenarios.map(item => ({ ...item, removed_gids: [gids[0]], removed_edge_sum_kzt: 250, removed_edge_sum_share: 1 }));
  const full = parseResilience(selfLoop, new Set([gids[0]]), 1)!;
  assert.equal(full.baseline.isolated_nodes, 1); assert.equal(full.scenarios[0].remaining_edges, 0);
  assert.equal(full.scenarios[0].removed_edge_sum_kzt, 250);
});

test('renders analyst labels, original client links and the complete limitation without superiority claims', () => {
  const html = renderToStaticMarkup(createElement(ResiliencePanel, { resilience: parseResilience(star(), nodeIds, 4)!, onSelectClient: () => {}, onShowOriginal: () => {} }));
  for (const text of ['Устойчивость наблюдаемой сети', 'По приоритету', 'По объёму переводов',
    'среди оставшихся клиентов', 'без учёта направления переводов', 'Показать исходный граф',
    `Открыть карточку клиента ${gids[0]}`, resilienceCaveat, 'Фактически исключено: 1.']) assert.ok(html.includes(text), text);
  assert.ok(!html.includes('лучше')); assert.ok(!html.includes('предотвращённый ущерб'));
});
