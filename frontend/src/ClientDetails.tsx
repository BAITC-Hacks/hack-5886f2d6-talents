import { ArrowDownLeft, ArrowUpRight, Info } from 'lucide-react';
import { clientLimitations, roleColors, roleNames, type Client } from './data';
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const score = (n: number) => n.toFixed(3);
const value = (n: number | null, suffix = '') => n === null ? 'Нет данных' : number.format(n) + suffix;
const breakdownNames: Record<string, string> = { seed_reach: 'Охват seed', volume: 'Объём переводов', counterparties: 'Контрагенты', external_clusters: 'Связи между кластерами' };
export function RoleLabel({ client }: { client: Client }) {
  return <span className="role-label"><i style={{ background: roleColors[client.role] }} />{roleNames[client.role]}</span>;
}
export default function ClientDetails({ client }: { client: Client }) {
  const warnings = clientLimitations(client);
  const alternatives = client.candidates.filter(candidate => candidate.role !== client.role);
  return <aside className="details-panel" aria-label="Карточка клиента">
    <div className="panel-heading"><span className="eyebrow">КАРТОЧКА КЛИЕНТА</span><span className="cluster-tag">Кластер {client.cluster}</span></div>
    <h2 className="client-gid">{client.gid}</h2>
    <RoleLabel client={client} />
    <div className="scores">
      <div><span>Приоритет проверки</span><strong>{score(client.priority_score)}<small> / 1</small></strong><div className="score-track"><i style={{ width: client.priority_score * 100 + '%' }} /></div></div>
      <div><span>Сила признаков роли</span><strong>{score(client.role_score)}<small> / 1</small></strong><div className="score-track secondary"><i style={{ width: client.role_score * 100 + '%' }} /></div></div>
    </div>
    <section className="explanation"><h3>Почему эта роль</h3><p>{client.evidence}</p></section>
    <section className="priority-explanation"><h3>Почему проверять</h3><p>{client.why}</p></section>
    <details className="breakdown"><summary>Из чего состоит приоритет</summary>
      {Object.keys(client.breakdown).length ? <><p className="muted">Вклады из аналитического ядра, без пересчёта.</p>
        {Object.entries(client.breakdown).map(([key, part]) => <div className="contribution" key={key}><span>{breakdownNames[key] ?? key}<small>Сигнал {score(part.signal)} × вес {score(part.weight)}</small></span><strong>{score(part.contribution)}</strong></div>)}</> : <p>Пайплайн не передал детализацию приоритета.</p>}
    </details>
    <section className="metrics-section"><h3>Переводы в выгрузке</h3>
      <div className="money-row"><ArrowDownLeft size={18}/><span>Входящие<strong>{value(client.total_in, ' ₸')}</strong></span></div>
      <div className="money-row outgoing"><ArrowUpRight size={18}/><span>Исходящие<strong>{value(client.total_out, ' ₸')}</strong></span></div>
      <p className="muted">Исходные суммы стартера, включая переводы себе. Не баланс счёта.</p>
      <dl className="facts">
        <div><dt>Отправителей / получателей</dt><dd>{value(client.in_count)} / {value(client.out_count)}</dd></div>
        <div><dt>Транзакций вход / выход</dt><dd>{value(client.in_tx)} / {value(client.out_tx)}</dd></div>
        <div><dt>Контрагентов без себя</dt><dd>{value(client.counterparties)}</dd></div>
        <div><dt>Достижим из seed</dt><dd>{value(client.seed_reach)}</dd></div>
        <div><dt>Шагов от другого seed</dt><dd>{value(client.min_seed_hops)}</dd></div>
        <div><dt>Глубина · depth</dt><dd>{value(client.depth)}</dd></div>
        <div><dt>Исходный клиент · is_seed</dt><dd>{client.is_seed ? 'Да' : 'Нет'}</dd></div>
      </dl>
      <details><summary>Суммы без переводов себе</summary><dl className="facts"><div><dt>Наблюдаемые входящие</dt><dd>{value(client.observed_in, ' ₸')}</dd></div><div><dt>Наблюдаемые исходящие</dt><dd>{value(client.observed_out, ' ₸')}</dd></div></dl></details>
    </section>
    {alternatives.length > 0 && <details className="alternative"><summary>Другие подходящие роли</summary>{alternatives.map((c, i) => <p key={c.role + i}>{roleNames[c.role]} · {score(c.score)}</p>)}</details>}
    <section className="limitations"><h3><Info size={16}/> Ограничения данных</h3>
      {warnings.length ? <ul>{warnings.map(w => <li key={w}>{w}</li>)}</ul> : <p>Дополнительных ограничений для клиента не передано. Общие ограничения выборки сохраняются.</p>}
    </section>
  </aside>;
}
