import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import TransferDetails from './TransferDetails';
import { findTransfer, transferKey } from './transfers';
import type { Transfer } from './data';

const forward: Transfer = { source: '9007199254740992', target: '9007199254740993', amount: 12345.67, transactions: 3 };
const reverse: Transfer = { source: forward.target, target: forward.source, amount: 890, transactions: 1 };

test('directed selection survives reordering and never switches to another edge after filtering', () => {
  const key = transferKey(forward);
  assert.notEqual(key, transferKey(reverse));
  assert.equal(findTransfer([reverse, forward], key), forward);
  assert.equal(findTransfer([reverse], key), undefined);
  assert.equal(findTransfer([forward], transferKey(reverse)), undefined);
  assert.equal(findTransfer([forward, reverse], null), undefined);
  assert.notEqual(transferKey({ source: 'a:b', target: 'c' }), transferKey({ source: 'a', target: 'b:c' }));
});

function card(transfer: Transfer, opposite?: Transfer) {
  return renderToStaticMarkup(createElement(TransferDetails, { transfer, reverse: opposite,
    onSelectClient: () => {}, onClose: () => {}, onReverse: () => {} })).replaceAll('&#x27;', "'");
}
test('transfer card shows exact full IDs, independent amounts and counts in each direction', () => {
  const html = card(forward, reverse);
  assert.ok(html.indexOf(forward.source) < html.indexOf(forward.target));
  assert.ok(html.includes(new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(12345.67) + ' ₸'));
  assert.match(html, /Количество переводов<\/dt><dd>3<\/dd>/);
  assert.match(html, /Показать встречные переводы/);
  const reversed = card(reverse, forward);
  assert.ok(reversed.indexOf(reverse.source) < reversed.indexOf(reverse.target));
  assert.match(reversed, /890,00 ₸/);
  assert.match(reversed, /Количество переводов<\/dt><dd>1<\/dd>/);
});
test('unavailable edge metrics remain unavailable, and a self transfer has no reverse action', () => {
  const html = card({ ...forward, amount: null, transactions: null });
  assert.equal(html.match(/Нет данных/g)?.length, 2);
  const self = card({ ...forward, target: forward.source });
  assert.match(self, /Перевод самому себе/);
  assert.doesNotMatch(self, /Показать встречные переводы/);
});
