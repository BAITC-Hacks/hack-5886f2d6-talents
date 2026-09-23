import { useState } from 'react';
import { resilienceCounts, resilienceScenario, type Resilience, type ResilienceK, type ResilienceStrategy, type Scenario } from './resilience';

const count = new Intl.NumberFormat('ru-RU');
const amount = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const share = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 2 });
export const resilienceCaveat = 'Структурный эксперимент на неполной наблюдаемой сети. Он не доказывает прекращение переводов или деятельности группы. Удалённый оборот — прошлые наблюдаемые операции, не предотвращённые потери';
const strategyNames = { priority: 'По приоритету', volume: 'По объёму переводов' };

export function ResilienceComparison({ baseline, scenario }: { baseline: Scenario; scenario: Scenario }) {
  return <div className="resilience-comparison"><table>
    <caption>Исходная сеть и модель после исключения выбранных клиентов</caption>
    <thead><tr><th scope="col">Показатель</th><th scope="col">До</th><th scope="col">После</th></tr></thead>
    <tbody>
      <tr><th scope="row">Крупнейшая связанная группа</th>{[baseline, scenario].map((item, index) => <td key={index}><strong>{count.format(item.largest_component_nodes)} клиентов</strong><small>{share.format(item.largest_component_share_remaining)} среди оставшихся клиентов</small></td>)}</tr>
      <tr><th scope="row">Связанные группы <small>(слабые компоненты)</small></th><td>{count.format(baseline.weak_components)}</td><td>{count.format(scenario.weak_components)}</td></tr>
      <tr><th scope="row">Клиенты без внешних связей</th><td>{count.format(baseline.isolated_nodes)}</td><td>{count.format(scenario.isolated_nodes)}</td></tr>
      <tr><th scope="row">Оставшиеся клиенты</th><td>{count.format(baseline.remaining_nodes)}</td><td>{count.format(scenario.remaining_nodes)}</td></tr>
      <tr><th scope="row">Оставшиеся направленные связи</th><td>{count.format(baseline.remaining_edges)}</td><td>{count.format(scenario.remaining_edges)}</td></tr>
      <tr><th scope="row">Прошлые операции на исключённых связях</th>{[baseline, scenario].map((item, index) => <td key={index}><strong>{amount.format(item.removed_edge_sum_kzt)} ₸</strong><small>{share.format(item.removed_edge_sum_share)} общей суммы наблюдаемых переводов</small></td>)}</tr>
    </tbody>
  </table></div>;
}

export default function ResiliencePanel({ resilience, onSelectClient, onShowOriginal }: {
  resilience: Resilience;
  onSelectClient: (gid: string) => void;
  onShowOriginal: () => void;
}) {
  const [strategy, setStrategy] = useState<ResilienceStrategy>('priority');
  const [selectedCount, setSelectedCount] = useState<ResilienceK>(1);
  const scenario = resilienceScenario(resilience, strategy, selectedCount);
  return <details className="resilience-panel">
    <summary className="resilience-heading"><span>Устойчивость наблюдаемой сети</span><small>Что меняется при исключении клиентов — 8 готовых сценариев</small></summary>
    <div className="resilience-body">
      <p className="resilience-note">Сравните два способа отбора. Исключение действует только в модели: исходный граф, карточки клиентов и файлы сохранены. Связанные группы считаются без учёта направления переводов.</p>
      <div className="resilience-controls">
        <label>Способ отбора<select aria-label="Способ отбора в структурном эксперименте" value={strategy} onChange={event => setStrategy(event.target.value as ResilienceStrategy)}>
          <option value="priority">По приоритету</option><option value="volume">По объёму переводов</option>
        </select></label>
        <label>Сколько клиентов исключить (N)<select aria-label="Сколько клиентов исключить (N)" value={selectedCount} onChange={event => setSelectedCount(Number(event.target.value) as ResilienceK)}>
          {resilienceCounts.map(value => <option value={value} key={value}>{value}</option>)}
        </select></label>
      </div>
      <p className="resilience-selection" role="status">{strategyNames[strategy]}. Запрошено: {selectedCount}. Фактически исключено: {scenario.removed_gids.length}.</p>
      <ResilienceComparison baseline={resilience.baseline} scenario={scenario} />
      <div className="resilience-removed"><h3>Исключённые в модели клиенты</h3>
        <p className="resilience-note">Откройте карточку, чтобы проверить причины приоритета и исходные связи.</p>
        {scenario.removed_gids.length ? <div className="resilience-gids">{scenario.removed_gids.map(gid => <button type="button" key={gid} onClick={() => onSelectClient(gid)} aria-label={`Открыть карточку клиента ${gid}`}>{gid}</button>)}</div> : <p>В этой модели нет исключённых клиентов.</p>}
      </div>
      <button type="button" className="resilience-original" onClick={onShowOriginal}>Показать исходный граф</button>
      <p className="resilience-caveat">{resilienceCaveat}.</p>
    </div>
  </details>;
}
