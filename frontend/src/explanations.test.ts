import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseGraph } from './data';
import ClientDetails from './ClientDetails';
import { roleExplanation, priorityExplanation, prioritySummary, plainLanguage } from './explanations';

const raw = JSON.parse(readFileSync(new URL('../public/data/graph.json', import.meta.url), 'utf8'));
const data = parseGraph(raw);
const client = (gid: string) => data.nodes.find(node => node.gid === gid)!;
const compact = (text: string) => text.replace(/\s/g, ' ');

test('leader uses readable sentences while retaining exact original explanations and ranking', () => {
  const leader = client('100000000331309100');
  const before = structuredClone(leader);
  const explanation = compact(roleExplanation(leader));
  assert.match(explanation, /от 5 отправителей/);
  assert.match(explanation, /99 получателям/);
  assert.match(explanation, /от 7 исходных клиентов/);
  assert.match(explanation, /13 другими группами/);
  assert.match(priorityExplanation(leader), /23.001.375 ₸/);
  assert.doesNotMatch(priorityExplanation(leader), /seed|max\(/);
  assert.doesNotMatch(prioritySummary(leader), /seed|достижим/);
  const html = renderToStaticMarkup(createElement(ClientDetails, { client: leader }));
  assert.ok(html.includes(leader.evidence));
  assert.ok(html.includes(leader.why));
  assert.ok(html.includes('Исходные формулировки расчёта'));
  assert.deepEqual(leader, before);
});

test('renders precomputed ratio as percent without claiming the same money or calculating a missing ratio', () => {
  const transit = client('100000008692291100');
  assert.match(compact(roleExplanation(transit)), /160 000 ₸.*156 000 ₸/);
  assert.match(roleExplanation(transit), /97,5.*%/);
  assert.match(roleExplanation(transit), /не доказывают.*те же деньги/);
  assert.doesNotMatch(roleExplanation({ ...transit, pass_through: null }), /%/);
  // Deliberately differing prepared ratio: presentation must not divide sums itself.
  assert.match(roleExplanation({ ...transit, nonself_in: 11, pass_through: 0.03 }), /от 11 отправителей.*3.*%/);
});

test('boundary, incomplete seed inflow and isolated clients retain meaningful qualifications', () => {
  const boundary = client('100000003037476100');
  assert.match(roleExplanation(boundary), /исходящие могут быть за границей выгрузки/);
  assert.match(prioritySummary(boundary), /Исходящие могут быть неполными/);
  const isolated = client('100000000456947100');
  assert.match(roleExplanation(isolated), /Входящих от других клиентов.*нет/);
  assert.match(roleExplanation(isolated), /Входящие этого исходного клиента могут быть неполными/);
  assert.equal(prioritySummary(isolated), 'Связей с другими клиентами в выгрузке нет.');
  const seed = data.nodes.find(node => node.is_seed && node.counterparties! > 0)!;
  assert.match(roleExplanation(seed), /Входящие.*могут быть неполными/);
});

test('all six supplied roles have readable explanations, with no formula shorthand in main copy', () => {
  for (const role of ['consolidator', 'transit', 'distributor', 'terminal', 'coordinator', 'peripheral']) {
    const node = data.nodes.find(node => node.role === role)!;
    assert.ok(node, role);
    assert.doesNotMatch(roleExplanation(node), /seed|достижим|отправителей\/получателей|max\(/i);
    assert.doesNotMatch(priorityExplanation(node), /seed|достижим|max\(/i);
  }
});

test('wording changes preserve action order, future text and safe React escaping', () => {
  const action = 'Проверить направленные маршруты от 7 seed и связи с 13 внешними кластерами; сопоставить даты операций.';
  assert.equal(plainLanguage(action), 'Проверить цепочки переводов от 7 исходных клиентов и связи с 13 другими группами клиентов; сопоставить даты операций.');
  assert.equal(plainLanguage('Новый неизвестный совет.'), 'Новый неизвестный совет.');
  const leader = client('100000000331309100');
  const html = renderToStaticMarkup(createElement(ClientDetails, { client: { ...leader, next_actions: ['<img src=x onerror=alert(1)>'] } }));
  assert.ok(!html.includes('<img'));
  const fallback = { ...leader, nonself_in: null, evidence: 'Новый вариант объяснения от ядра.' };
  assert.equal(roleExplanation(fallback), fallback.evidence);
});
