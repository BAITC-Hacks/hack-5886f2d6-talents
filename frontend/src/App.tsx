import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Download, Filter, Info, Network, RefreshCw, Search, ShieldCheck, SlidersHorizontal, Users } from 'lucide-react';
import ResiliencePanel from './ResiliencePanel';
import { plainLanguage, prioritySummary } from './explanations';
import GraphView from './GraphView';
import TransferDetails from './TransferDetails';
import { findTransfer, transferKey } from './transfers';
import ClientDetails, { RoleLabel } from './ClientDetails';
import { buildNeighbors, clusterColor, neighborhood, roleColors, roleNames, roles, type GraphData, type Role } from './data';
import { csvFiles, loadGraphBundle } from './bundle';

const dataRoot = import.meta.env.BASE_URL + 'data/';
type ExportFile = { name: string; url: string };
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const score = (n: number) => n.toFixed(3);
export default function App() {
  const [data, setData] = useState<GraphData | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [exports, setExports] = useState<ExportFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedTransfer, setSelectedTransfer] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchMessage, setSearchMessage] = useState('');
  const [role, setRole] = useState<Role | 'all'>('all');
  const [cluster, setCluster] = useState('all');
  const [colorBy, setColorBy] = useState<'role' | 'cluster'>('role');
  const [scope, setScope] = useState<'cluster' | 'neighbors' | 'all'>('cluster');
  const [hops, setHops] = useState(1);
  const [listMode, setListMode] = useState<'top' | 'all'>('top');
  const [limit, setLimit] = useState(50);
  useEffect(() => {
    const controller = new AbortController();
    const objectUrls: string[] = [];
    setError(''); setData(null); setExports([]); setSelectedTransfer(null);
    async function load() {
      try {
        const bundle = await loadGraphBundle(dataRoot, controller.signal);
        if (controller.signal.aborted) return;
        const graph = bundle.graph;
        const files = bundle.exports.map(file => {
          const url = URL.createObjectURL(new Blob([file.bytes], { type: 'text/csv;charset=utf-8' }));
          objectUrls.push(url);
          return { name: file.name, url };
        });
        setExports(files);
        setData(graph); setSelected(graph.top[0]?.gid ?? graph.nodes[0]?.gid ?? null);
        setRole('all'); setCluster('all'); setScope('cluster'); setSearchMessage('');
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Не удалось прочитать комплект расчёта');
      }
    }
    void load();
    return () => { controller.abort(); objectUrls.forEach(url => URL.revokeObjectURL(url)); };
  }, [reload]);
  const byId = useMemo(() => new Map(data?.nodes.map(n => [n.gid, n])), [data]);
  const neighbors = useMemo(() => buildNeighbors(data?.edges ?? []), [data]);
  const client = selected ? byId.get(selected) : undefined;
  const topRanks = useMemo(() => new Map(data?.top.map(t => [t.gid, t.rank])), [data]);
  const list = useMemo(() => {
    if (!data) return [];
    const source = listMode === 'top' ? data.top.map(t => byId.get(t.gid)!) : data.nodes;
    return source.filter(n => (role === 'all' || n.role === role) && (cluster === 'all' || n.cluster === cluster));
  }, [data, listMode, role, cluster, byId]);
  const focusCluster = cluster !== 'all' ? cluster : client?.cluster ?? data?.clusters[0]?.id;
  const visibleNodes = useMemo(() => {
    if (!data) return [];
    const around = selected && scope === 'neighbors' ? neighborhood(selected, neighbors, hops) : null;
    return data.nodes.filter(n => (role === 'all' || n.role === role) && (cluster === 'all' || n.cluster === cluster)
      && (scope === 'all' || (scope === 'cluster' ? n.cluster === focusCluster : around?.has(n.gid))));
  }, [data, role, cluster, scope, focusCluster, selected, neighbors, hops]);
  const visibleEdges = useMemo(() => {
    const ids = new Set(visibleNodes.map(n => n.gid));
    return data?.edges.filter(e => ids.has(e.source) && ids.has(e.target)) ?? [];
  }, [data, visibleNodes]);
  const transfer = findTransfer(visibleEdges, selectedTransfer);
  const reverseTransfer = transfer && transfer.source !== transfer.target
    ? visibleEdges.find(edge => edge.source === transfer.target && edge.target === transfer.source) : undefined;
  const activeCluster = data?.clusters.find(c => c.id === focusCluster);
  function selectClient(gid: string) {
    setSelectedTransfer(null); setSelected(gid); setScope('neighbors'); setHops(1); setRole('all'); setCluster('all'); setSearchMessage('');
  }
  function search(event: FormEvent) {
    event.preventDefault();
    const gid = query.trim();
    if (!gid) { setSearchMessage('Введите полный gid клиента.'); return; }
    if (!byId.has(gid)) { setSearchMessage('Клиент ' + gid + ' не найден в загруженной выгрузке.'); return; }
    selectClient(gid); setSearchMessage('Клиент найден. Фильтры сброшены, показаны все связи первого шага.');
  }
  function reset() { setSelectedTransfer(null); setRole('all'); setCluster('all'); setLimit(50); setSearchMessage(''); }
  if (!data) return <main className="loading-screen"><Network size={40}/><h1>Поток</h1>{error ? <><h2>Не удалось загрузить данные</h2><p role="alert">{error}</p><p>Завершите пересчёт файлов и повторите загрузку.</p><button onClick={() => setReload(n => n + 1)}>Повторить загрузку</button></> : <p role="status">Загружаем и проверяем граф переводов…</p>}</main>;
  return <div className="app">
    <header className="app-header">
      <div className="brand"><span className="brand-mark"><Network size={23}/></span><span>поток<small>АНАЛИЗ ПЕРЕВОДОВ</small></span></div>
      <div className="header-context">Рабочее место аналитика<span>HackAlem AI · TALENTS</span></div>
      <div className="header-actions"><span className={'dataset-badge ' + (data.meta.is_demo ? 'demo' : '')}>{data.meta.is_demo ? 'Учебный пример' : 'Данные пайплайна'}</span>
        <details className="exports"><summary><Download size={16}/> Экспорт CSV</summary><div className="export-menu"><strong>Выгрузки пайплайна</strong>{csvFiles.map(name => {
          const file = exports.find(f => f.name === name);
          return file ? <a key={name} href={file.url} download={name}><Download size={15}/><span>{name}<small>Скачать файл открытого расчёта</small></span></a> : <button key={name} disabled><Download size={15}/><span>{name}<small>Файл пока не передан</small></span></button>;
        })}<p>Экспортируется полная выгрузка, независимо от фильтров.</p></div></details>
      </div>
    </header>
    <main>
      <section className="page-heading"><div><div className="eyebrow">ИССЛЕДОВАНИЕ СЕТИ</div><h1>Кого проверить первым</h1><p>Приоритеты, связи и объяснения в одном месте.</p></div><div className="dataset-stats"><span><strong>{number.format(data.nodes.length)}</strong>клиентов</span><span><strong>{number.format(data.edges.length)}</strong>связей</span><span><strong>{data.clusters.length}</strong>кластеров</span></div></section>
      <div className="notice"><ShieldCheck size={17}/><span>Роли и оценки — гипотезы для проверки, а не утверждения о виновности.{data.meta.is_demo && ' Учебный режим: выводы не относятся к полному датасету.'}</span><details><summary>О данных</summary><div><p>Видна только часть переводов. Входящие исходных клиентов и исходящие на четвёртом шаге выгрузки могут быть неполными.</p><p>Полная выборка: внутрибанковские переводы ≥ 5 000 ₸, июль 2026, обход по исходящим на 4 шага.</p><p>Версия ядра: {data.meta.engine}.</p>{data.meta.limitations.map((s, i) => <p key={i}>{plainLanguage(s)}</p>)}</div></details></div>
      <section className="toolbar" aria-label="Поиск и фильтры">
        <form className="search-form" onSubmit={search}><Search size={18}/><input aria-label="Поиск по точному gid" placeholder="Найти клиента по полному gid" value={query} onChange={e => setQuery(e.target.value)} autoComplete="off"/><button type="submit">Найти</button></form>
        <div className="filter-controls"><Filter size={16}/><label><span className="sr-only">Фильтр по роли</span><select aria-label="Фильтр по роли" value={role} onChange={e => { setSelectedTransfer(null); setRole(e.target.value as Role | 'all'); setLimit(50); }}><option value="all">Все роли</option>{roles.map(r => <option key={r} value={r}>{roleNames[r]}</option>)}</select></label>
        <label><span className="sr-only">Фильтр по кластеру</span><select aria-label="Фильтр по кластеру" value={cluster} onChange={e => { setSelectedTransfer(null); setCluster(e.target.value); setScope(e.target.value === 'all' ? 'all' : 'cluster'); setLimit(50); }}><option value="all">Все кластеры</option>{data.clusters.map(c => <option key={c.id} value={c.id}>Кластер {c.id} · {c.count}</option>)}</select></label><button className="icon-button" aria-label="Сбросить фильтры" onClick={reset}><RefreshCw size={16}/></button></div>
      </section>
      {searchMessage && <p className="search-message" role="status">{searchMessage}</p>}
      {data.meta.resilience && <ResiliencePanel resilience={data.meta.resilience} onSelectClient={selectClient} onShowOriginal={() => { reset(); setScope('all'); }}/>}
      <div className="workspace">
        <aside className="priority-panel" aria-label="Список клиентов">
          <div className="panel-heading"><h2>Приоритеты</h2><span className="count">{data.top.length}</span></div>
          <div className="list-tabs"><button className={listMode === 'top' ? 'active' : ''} onClick={() => { setListMode('top'); setLimit(50); }}>Топ {data.top.length}</button><button className={listMode === 'all' ? 'active' : ''} onClick={() => { setListMode('all'); setLimit(50); }}>Все клиенты</button></div>
          <p className="list-caption">{listMode === 'top' ? 'Очередь проверки из расчёта' : 'Порядок исходной выгрузки'} · {list.length}</p>
          <div className="client-list">
            {list.slice(0, limit).map(node => <button className={'client-row ' + (selected === node.gid ? 'selected' : '')} key={node.gid} onClick={() => selectClient(node.gid)} aria-pressed={selected === node.gid} aria-label={'Выбрать клиента ' + node.gid}>
              <span className="rank">{topRanks.get(node.gid) ? String(topRanks.get(node.gid)).padStart(2, '0') : '·'}</span><span className="row-main"><span className="row-gid">{node.gid}</span><RoleLabel client={node}/><span className="row-reason">{prioritySummary(node)}</span><span className="row-meta">Кластер {node.cluster} · шаг {node.depth ?? 'Нет данных'}</span></span><span className="row-score">{score(node.priority_score)}</span>
            </button>)}
            {list.length === 0 && <div className="empty-list"><Users size={25}/><p>Нет клиентов по этим фильтрам.</p><button onClick={reset}>Сбросить фильтры</button></div>}
            {list.length > limit && <button className="load-more" onClick={() => setLimit(n => n + 50)}>Показать ещё 50</button>}
          </div>
          <div className="list-footer"><Info size={14}/><span>{data.meta.is_demo ? 'Учебный набор: ' + data.nodes.length + ' клиентов. На полном наборе — топ не менее 20.' : 'Низкий приоритет не исключает необходимость проверки.'}</span></div>
        </aside>
        <section className="graph-panel" aria-label="Граф переводов">
          <div className="panel-heading"><div><h2>Связи клиентов</h2><p>{visibleNodes.length} узлов · {visibleEdges.length} направленных связей</p></div><Network size={20}/></div>
          <div className="graph-toolbar"><div className="view-tabs"><button className={scope === 'cluster' ? 'active' : ''} onClick={() => { setSelectedTransfer(null); setScope('cluster'); }}>Кластер</button><button disabled={!client} className={scope === 'neighbors' ? 'active' : ''} onClick={() => { setSelectedTransfer(null); setScope('neighbors'); }}>Окружение</button><button className={scope === 'all' ? 'active' : ''} onClick={() => { setSelectedTransfer(null); setScope('all'); }}>Общий граф</button></div><label className="color-select"><SlidersHorizontal size={14}/><select aria-label="Раскраска графа" value={colorBy} onChange={e => setColorBy(e.target.value as 'role' | 'cluster')}><option value="role">По роли</option><option value="cluster">По кластеру</option></select></label></div>
          {scope === 'neighbors' && <div className="scope-description">Связи в обоих направлениях <button onClick={() => { setSelectedTransfer(null); setHops(n => n === 1 ? 2 : 1); }}>{hops === 1 ? 'Раскрыть 2 шага' : 'Оставить 1 шаг'}</button><span>Сейчас: {hops}</span></div>}
          {client && !visibleNodes.some(n => n.gid === client.gid) && <div className="scope-description">Выбранный клиент вне текущего вида. <button onClick={() => selectClient(client.gid)}>Показать его связи</button></div>}
          <label className="transfer-picker"><span>Связь на графе</span><select aria-label="Выбрать направленную связь" disabled={visibleEdges.length === 0} value={transfer ? transferKey(transfer) : ''} onChange={e => setSelectedTransfer(e.target.value || null)}>
            <option value="">{visibleEdges.length ? 'Нажмите на стрелку или выберите связь' : 'В этом виде нет связей'}</option>
            {visibleEdges.map(edge => <option key={transferKey(edge)} value={transferKey(edge)}>{edge.source} → {edge.target}</option>)}
          </select></label>
          <GraphView nodes={visibleNodes} edges={visibleEdges} selected={selected} selectedTransfer={transfer ? transferKey(transfer) : null} onSelectTransfer={setSelectedTransfer} colorBy={colorBy} onSelect={selectClient} overview={scope === 'all'}/>
          <div className="legend">{colorBy === 'role' ? roles.map(r => <span key={r}><i style={{ background: roleColors[r] }}/>{roleNames[r]}</span>) : <><span>Цвет обозначает кластер</span>{[...new Set(visibleNodes.map(n => n.cluster))].slice(0, 12).map(c => <span key={c}><i style={{ background: clusterColor(c) }}/>Кластер {c}</span>)}{new Set(visibleNodes.map(n => n.cluster)).size > 12 && <span>Остальные — в фильтре</span>}</>}</div>
          {scope === 'cluster' && activeCluster && <div className="cluster-summary"><strong>Кластер {activeCluster.id}</strong><span>{activeCluster.count} клиентов · {activeCluster.seeds} исходных клиентов · {number.format(activeCluster.amount)} ₸ внутри</span><p>{plainLanguage(activeCluster.hypothesis)}</p></div>}
          <div className="graph-footer">Фильтры скрывают часть связей. В карточке — полные метрики из файла.</div>
        </section>
        {transfer ? <TransferDetails key={transferKey(transfer)} transfer={transfer} reverse={reverseTransfer} onSelectClient={selectClient} onReverse={() => { if (reverseTransfer) setSelectedTransfer(transferKey(reverseTransfer)); }} onClose={() => setSelectedTransfer(null)}/> : client ? <ClientDetails key={client.gid} client={client}/> : <aside className="details-panel empty-details"><Network size={32}/><h2>Выберите клиента</h2><p>Нажмите на узел, строку списка или найдите полный gid.</p></aside>}
      </div>
      <footer className="app-footer"><span>Локальный анализ · без внешних API</span><button onClick={() => setReload(n => n + 1)}><RefreshCw size={13}/> Обновить файлы</button></footer>
    </main>
  </div>;
}
