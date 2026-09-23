import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ClientDetails from './ClientDetails';
import { parseGraph, buildNeighbors, neighborhood, clientLimitations } from './data';
const example = () => JSON.parse(readFileSync(new URL('../../examples/graph.json', import.meta.url), 'utf8'));
test('accepts the exact agreed C++/Python example without changing IDs, scores or top order', () => {
  const raw = example(), data = parseGraph(raw);
  assert.equal(data.nodes[0].gid, '100000000000000001');
  assert.deepEqual(data.top.map(n => n.gid), raw.top_nodes.map((n: {gid: string}) => n.gid));
  for (const node of data.nodes) {
    const original = raw.nodes.find((n: {gid: string}) => n.gid === node.gid);
    assert.equal(node.priority_score, original.priority_score);
    assert.equal(node.total_in, original.in_kzt);
    assert.equal(node.evidence, original.evidence);
    assert.deepEqual(node.breakdown, original.priority_breakdown);
  }
});
test('rejects numeric/duplicate IDs, unknown endpoints and stale top entries', () => {
  const numeric = example(); numeric.nodes[0].gid = 100000000000000001;
  assert.throws(() => parseGraph(numeric), /gid/);
  const duplicate = example(); duplicate.nodes.push(duplicate.nodes[0]);
  assert.throws(() => parseGraph(duplicate), /gid/);
  const unknown = example(); unknown.edges[0].dst = 'missing';
  assert.throws(() => parseGraph(unknown), /src\/dst/);
  const stale = example(); stale.top_nodes[0].priority_score = 0.111;
  assert.throws(() => parseGraph(stale), /Топ/);
});
test('keeps an isolated seed searchable and null distances unavailable', () => {
  const data = parseGraph(example()), isolated = data.nodes.find(n => n.gid === '100000000000000004')!;
  assert.deepEqual([...neighborhood(isolated.gid, buildNeighbors(data.edges), 2)], [isolated.gid]);
  assert.equal(isolated.min_seed_hops, null);
  assert.ok(clientLimitations(isolated).some(w => w.includes('нет связей')));
  assert.ok(clientLimitations(isolated).some(w => w.includes('входящие')));
});
test('expands incoming and outgoing neighbors while preserving directed edges', () => {
  const data = parseGraph(example()), map = buildNeighbors(data.edges);
  assert.deepEqual([...neighborhood('100000000000000002', map, 1)].sort(),
    ['100000000000000001', '100000000000000002', '100000000000000003']);
  assert.equal(data.edges[0].source, '100000000000000001');
  assert.equal(data.edges[0].target, '100000000000000002');
});
test('depth=4 still warns if its warning code is missing, and unknown codes remain visible', () => {
  const data = parseGraph(example()), boundary = data.nodes.find(n => n.depth === 4)!;
  boundary.warnings = ['NEW_LIMIT'];
  const limitations = clientLimitations(boundary);
  assert.ok(limitations.some(w => w.includes('Граница обхода')));
  assert.ok(limitations.some(w => w.includes('NEW_LIMIT')));
});
test('uses flat canonical metrics even if compatibility metrics disagree', () => {
  const raw = example(); raw.nodes[0].metrics.in_kzt = 999999;
  assert.equal(parseGraph(raw).nodes[0].total_in, raw.nodes[0].in_kzt);
});
test('validates full pipeline delivery and the four documented demo cases when available', () => {
  const path = new URL('../public/data/graph.json', import.meta.url);
  if (!existsSync(path)) return;
  const data = parseGraph(JSON.parse(readFileSync(path, 'utf8')));
  if (data.meta.is_demo) return;
  assert.equal(data.nodes.length, 2248); assert.equal(data.edges.length, 3119);
  assert.ok(data.top.length >= 20);
  for (const [gid, role] of [['100000000331309100','coordinator'], ['100000008692291100','transit'], ['100000003037476100','consolidator'], ['100000000456947100','peripheral']]) {
    assert.equal(data.nodes.find(n => n.gid === gid)?.role, role);
  }
});

test('preserves next actions exactly in pipeline order without deriving or deduplicating them', () => {
  const raw = example();
  const actions = ['Проверить маршруты от разных seed.', ' Запросить продолжение исходящих.\nСверить период. ', 'Проверить маршруты от разных seed.'];
  raw.nodes[0].next_actions = actions;
  const client = parseGraph(raw).nodes[0];
  assert.deepEqual(client.next_actions, actions);
  assert.equal(client.evidence, raw.nodes[0].evidence);
  assert.equal(client.priority_score, raw.nodes[0].priority_score);
  const html = renderToStaticMarkup(createElement(ClientDetails, { client }));
  assert.ok(html.includes('<h3>Что проверить дальше</h3><ol><li>' + actions.join('</li><li>') + '</li></ol>'));
});
test('accepts older bundles without next actions and distinguishes an explicit empty list', () => {
  const raw = example();
  for (const node of raw.nodes) delete node.next_actions;
  const oldData = parseGraph(raw);
  for (const client of oldData.nodes) {
    assert.equal(client.next_actions, undefined);
    const html = renderToStaticMarkup(createElement(ClientDetails, { client }));
    assert.ok(!html.includes('Что проверить дальше'));
  }
  raw.nodes[0].next_actions = [];
  const empty = parseGraph(raw).nodes[0];
  assert.deepEqual(empty.next_actions, []);
  assert.ok(!renderToStaticMarkup(createElement(ClientDetails, { client: empty })).includes('Что проверить дальше'));
});
test('rejects malformed supplied next actions with a node-specific field error', () => {
  for (const invalid of [null, undefined, 'Проверить', {}, [1], ['Проверить', false]]) {
    const raw = example(); raw.nodes[0].next_actions = invalid;
    assert.throws(() => parseGraph(raw), /100000000000000001\.next_actions: ожидается массив строк/);
  }
});
test('renders supplied next actions as text, never as markup', () => {
  const raw = example(); raw.nodes[0].next_actions = ['<script>alert("test")</script>'];
  const html = renderToStaticMarkup(createElement(ClientDetails, { client: parseGraph(raw).nodes[0] }));
  assert.ok(html.includes('&lt;script&gt;alert(&quot;test&quot;)&lt;/script&gt;'));
  assert.ok(!html.includes('<script>'));
});
test('rejects duplicate directed pairs while preserving reciprocal transfers', () => {
  const duplicate = example(); duplicate.edges.push({ ...duplicate.edges[0] });
  assert.throws(() => parseGraph(duplicate), /повторная направленная пара src\/dst/);
  const reciprocal = example(), first = reciprocal.edges[0];
  reciprocal.edges = [first, { ...first, src: first.dst, dst: first.src, sum_kzt: 123, n_tx: 2 }];
  const data = parseGraph(reciprocal);
  assert.equal(data.edges.length, 2);
  assert.deepEqual(data.edges[1], { source: first.dst, target: first.src, amount: 123, transactions: 2 });
});
