import type { Client } from './data';

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const money = (value: number) => number.format(value) + ' ₸';
const known = (value: number | null | undefined): value is number => value !== null && value !== undefined;
export function counted(value: number, one: string, few: string, many: string): string {
  const last = value % 10, lastTwo = value % 100;
  return number.format(value) + ' ' + (lastTwo >= 11 && lastTwo <= 14 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many);
}
const senders = (value: number) => counted(value, 'отправителя', 'отправителей', 'отправителей');
const receivers = (value: number) => counted(value, 'получателю', 'получателям', 'получателям');
const origins = (value: number) => counted(value, 'исходного клиента', 'исходных клиентов', 'исходных клиентов');

// Presentation of supplied facts only: no role selection, ranking or ratio calculation.
export function plainLanguage(text: string): string {
  return text
    .replace(/направленные маршруты от (\d+) seed/g, (_, count: string) => 'цепочки переводов от ' + origins(Number(count)))
    .replace(/достижим из (\d+) seed/g, (_, count: string) => 'к нему ведут цепочки переводов от ' + origins(Number(count)))
    .replace(/переводы seed/g, 'переводы исходного клиента')
    .replace(/Seed: входящие неполны\./g, 'У исходного клиента входящие переводы могут быть неполными.')
    .replace(/от разных seed/g, 'от разных исходных клиентов')
    .replace(/seed/gi, 'исходные клиенты')
    .replace(/внешними кластерами/g, 'другими группами клиентов')
    .replace(/внешних кластеров/g, 'других групп клиентов')
    .replace(/\(depth=(\d+)\)/g, '(шаг $1 от начала выгрузки)')
    .replace(/depth=(\d+)/g, 'на шаге $1')
    .replace(/\bKZT\b/g, '₸');
}
function ratioSentence(client: Client): string {
  if (!known(client.pass_through)) return '';
  const text = 'Сумма исходящих — ' + percent.format(client.pass_through) + ' от суммы входящих.';
  if (client.depth === 4) return text + ' Дальнейшие исходящие могут быть за границей выгрузки.';
  if (client.is_seed) return text + ' Входящие исходного клиента могут быть неполными.';
  if (client.pass_through > 1) return text + ' Виден только фрагмент операций, не полный баланс счёта.';
  return text;
}
function flowSentence(client: Client): string | null {
  if (!known(client.nonself_in) || !known(client.nonself_out)) return null;
  const incoming = client.nonself_in === 0 ? 'Входящих от других клиентов в выгрузке нет' : 'Получает ' + (known(client.observed_in) ? money(client.observed_in) : 'переводы') + ' от ' + senders(client.nonself_in);
  const outgoing = client.nonself_out === 0 ? 'Исходящих другим клиентам в выгрузке нет.' : 'Отправляет ' + (known(client.observed_out) ? money(client.observed_out) : 'деньги') + ' ' + receivers(client.nonself_out) + '.';
  return incoming + '. ' + outgoing;
}
export function roleExplanation(client: Client): string {
  const flow = flowSentence(client);
  if (!flow) return plainLanguage(client.evidence);
  let text = flow;
  if (client.role === 'coordinator' && known(client.seed_reach) && known(client.external_clusters)) {
    text += ' К нему ведут цепочки переводов от ' + origins(client.seed_reach) + '; есть связи с ' + counted(client.external_clusters, 'другой группой', 'другими группами', 'другими группами') + ' клиентов.';
  } else if (client.role === 'peripheral') {
    text += ' Этих наблюдений недостаточно, чтобы выделить выраженную роль клиента.';
  } else {
    const ratio = ratioSentence(client);
    if (ratio) text += ' ' + ratio;
    if (client.role === 'transit') text += ' Похожие суммы ещё не доказывают, что дальше переведены те же деньги: нужно сопоставить даты операций.';
    if (client.role === 'terminal') text += ' Это гипотеза конечного получателя только в пределах выгрузки.';
  }
  if (client.depth === 4 && (client.role === 'coordinator' || client.role === 'peripheral' || !known(client.pass_through))) text += ' Дальнейшие исходящие могут быть за границей выгрузки.';
  if (client.is_seed && (client.role === 'coordinator' || client.role === 'peripheral' || !known(client.pass_through))) text += ' Входящие этого исходного клиента могут быть неполными.';
  return text;
}
export function priorityExplanation(client: Client): string {
  const match = /^Приоритет проверки: достижим из (\d+) seed; max\(вход,выход\)=([\d.eE+-]+) KZT; контрагентов (\d+); внешних кластеров (\d+)\.$/.exec(client.why);
  if (!match) return plainLanguage(client.why);
  const [, reach, volume, peers, groups] = match;
  const reachCount = Number(reach);
  const route = reachCount ? 'К клиенту ведут цепочки переводов от ' + origins(reachCount) + '.' : 'Цепочек от исходных клиентов к этому клиенту в выгрузке не найдено.';
  return route + ' Учитываются также ' + counted(Number(peers), 'контрагент', 'контрагента', 'контрагентов') + ' и связи с другими группами клиентов: ' + groups + '. Объём, учтённый в приоритете, — ' + money(Number(volume)) + ' (большая из сумм входящих и исходящих).';
}
export function prioritySummary(client: Client): string {
  if (client.counterparties === 0) return 'Связей с другими клиентами в выгрузке нет.';
  if (client.role === 'coordinator' && known(client.seed_reach) && known(client.external_clusters)) return 'Цепочки от ' + origins(client.seed_reach) + '; связи с другими группами: ' + number.format(client.external_clusters) + '.';
  if (known(client.nonself_in) && known(client.nonself_out)) {
    let text = 'От ' + senders(client.nonself_in) + ' → ' + receivers(client.nonself_out) + '.';
    if (known(client.pass_through) && !client.is_seed && client.depth !== 4) text += client.pass_through > 1 ? ' Исходящие больше входящих; видна часть операций.' : ' Исходящие — ' + percent.format(client.pass_through) + ' входящих.';
    if (client.depth === 4) text += ' Исходящие могут быть неполными.';
    else if (client.is_seed) text += ' Входящие могут быть неполными.';
    return text;
  }
  return plainLanguage(client.evidence);
}

