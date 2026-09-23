export const roles = ['consolidator', 'transit', 'distributor', 'terminal', 'coordinator', 'peripheral'] as const;
export type Role = typeof roles[number];
export const roleNames: Record<Role, string> = {
  consolidator: 'Признаки консолидации', transit: 'Признаки транзита', distributor: 'Признаки распределения',
  terminal: 'Возможный конечный получатель', coordinator: 'Кандидат на координирующую роль', peripheral: 'Недостаточно признаков роли',
};
export const roleColors: Record<Role, string> = {
  consolidator: '#7661cf', transit: '#2188ae', distributor: '#d88d35',
  terminal: '#ce6675', coordinator: '#21977e', peripheral: '#8795a6',
};
export interface Contribution { signal: number; weight: number; contribution: number }
export interface Client {
  gid: string; role: Role; cluster: string; priority_score: number; role_score: number;
  evidence: string; why: string; warnings: string[]; next_actions?: string[];
  candidates: { role: Role; score: number }[]; breakdown: Record<string, Contribution>;
  total_in: number | null; total_out: number | null; observed_in: number | null; observed_out: number | null;
  in_count: number | null; out_count: number | null; in_tx: number | null; out_tx: number | null;
  counterparties: number | null; seed_reach: number | null; min_seed_hops: number | null;
  depth: number | null; is_seed: boolean;
}
export interface Transfer { source: string; target: string; amount: number | null; transactions: number | null }
export interface Cluster { id: string; count: number; seeds: number; amount: number; hypothesis: string }
export interface GraphData {
  meta: { is_demo: boolean; limitations: string[]; engine: string };
  nodes: Client[]; edges: Transfer[]; top: { rank: number; gid: string }[]; clusters: Cluster[];
}
type Obj = Record<string, unknown>;
const object = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
function strings(v: unknown, field: string): string[] {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.some(x => typeof x !== 'string')) throw new Error(field + ': ожидается массив строк');
  return v;
}
function amount(v: unknown, field: string, integer = false): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || (integer && !Number.isInteger(v))) throw new Error(field + ': ожидается неотрицательное число или null');
  return v;
}
function score(v: unknown, field: string): number {
  const n = amount(v, field);
  if (n === null || n > 1) throw new Error(field + ': ожидается оценка от 0 до 1');
  return n;
}
function text(v: unknown, field: string): string {
  if (typeof v !== 'string' || !v.trim()) throw new Error(field + ': ожидается непустая строка');
  return v;
}
export function parseGraph(raw: unknown): GraphData {
  if (!object(raw) || raw.schema_version !== '1.0' || !object(raw.meta) || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges) || !Array.isArray(raw.top_nodes) || !Array.isArray(raw.clusters)) throw new Error('Ожидается graph.json формата 1.0: meta, nodes, edges, top_nodes, clusters');
  const meta = raw.meta, isDemo = meta.is_demo ?? meta.demo;
  if (typeof isDemo !== 'boolean') throw new Error('В meta нужен явный флаг is_demo (или demo)');
  const ids = new Set<string>();
  const nodes = raw.nodes.map((value, i): Client => {
    if (!object(value)) throw new Error('Некорректный клиент ' + i);
    const n = value, metrics = n, f = object(n.features) ? n.features : {};
    if (typeof n.gid !== 'string' || !n.gid.trim() || ids.has(n.gid)) throw new Error('gid должен быть уникальной непустой строкой: ' + String(n.gid));
    ids.add(n.gid);
    if (!roles.includes(n.role as Role)) throw new Error('Неизвестная роль у ' + n.gid);
    if (!Number.isSafeInteger(n.cluster_id) || (n.cluster_id as number) < 0 || typeof n.is_seed !== 'boolean') throw new Error('Некорректные cluster_id/is_seed у ' + n.gid);
    const breakdown: Record<string, Contribution> = {};
    if (n.priority_breakdown !== undefined && !object(n.priority_breakdown)) throw new Error('Некорректный priority_breakdown');
    for (const [key, val] of Object.entries(n.priority_breakdown ?? {})) {
      if (!object(val)) throw new Error('Некорректный вклад ' + key);
      breakdown[key] = { signal: score(val.signal, key), weight: score(val.weight, key), contribution: score(val.contribution, key) };
    }
    const candidates = n.role_candidates ?? [];
    if (!Array.isArray(candidates)) throw new Error('Некорректный role_candidates');
    const warnings = strings(n.warnings, 'warnings');
    let nextActions: string[] | undefined;
    if (Object.hasOwn(n, 'next_actions')) {
      if (!Array.isArray(n.next_actions) || n.next_actions.some(action => typeof action !== 'string')) throw new Error(n.gid + '.next_actions: ожидается массив строк');
      nextActions = n.next_actions;
    }
    return { gid: n.gid, role: n.role as Role, cluster: String(n.cluster_id), is_seed: n.is_seed,
      priority_score: score(n.priority_score, n.gid + '.priority_score'), role_score: score(n.role_score, n.gid + '.role_score'),
      evidence: text(n.evidence, 'evidence'), why: text(n.why, 'why'), warnings, next_actions: nextActions, breakdown,
      candidates: candidates.map(c => {
        if (!object(c) || !roles.includes(c.role as Role)) throw new Error('Некорректная альтернативная роль');
        return { role: c.role as Role, score: score(c.score, 'role_candidates.score') };
      }),
      total_in: amount(metrics.in_kzt, 'in_kzt'), total_out: amount(metrics.out_kzt, 'out_kzt'),
      observed_in: amount(f.observed_in_kzt, 'observed_in_kzt'), observed_out: amount(f.observed_out_kzt, 'observed_out_kzt'),
      in_count: amount(metrics.in_deg, 'in_deg', true), out_count: amount(metrics.out_deg, 'out_deg', true),
      in_tx: amount(metrics.in_tx, 'in_tx', true), out_tx: amount(metrics.out_tx, 'out_tx', true),
      counterparties: amount(f.counterparty_count, 'counterparty_count', true),
      seed_reach: amount(f.seed_reach_count, 'seed_reach_count', true), min_seed_hops: amount(f.min_seed_hops, 'min_seed_hops', true),
      depth: amount(n.depth, 'depth', true) };
  });
  const transferPairs = new Set<string>();
  const edges = raw.edges.map((value, i): Transfer => {
    if (!object(value) || typeof value.src !== 'string' || typeof value.dst !== 'string' || !ids.has(value.src) || !ids.has(value.dst)) throw new Error('Связь ' + i + ': src/dst должны ссылаться на существующие строковые gid');
    const pair = JSON.stringify([value.src, value.dst]);
    if (transferPairs.has(pair)) throw new Error('Связь ' + i + ': повторная направленная пара src/dst');
    transferPairs.add(pair);
    return { source: value.src, target: value.dst, amount: amount(value.sum_kzt, 'sum_kzt'), transactions: amount(value.n_tx, 'n_tx', true) };
  });
  const indexed = new Map(nodes.map(n => [n.gid, n]));
  const topIds = new Set<string>();
  const top = raw.top_nodes.map((t, i) => {
    if (!object(t) || typeof t.gid !== 'string' || !ids.has(t.gid) || topIds.has(t.gid) || t.rank !== i + 1) throw new Error('Некорректная строка top_nodes: ' + i);
    if (t.priority_score !== indexed.get(t.gid)!.priority_score || t.role !== indexed.get(t.gid)!.role) throw new Error('Топ не соответствует узлу ' + t.gid);
    topIds.add(t.gid);
    return { rank: i + 1, gid: t.gid };
  });
  if (!isDemo && top.length < Math.min(20, nodes.length)) throw new Error('Полный результат должен содержать минимум 20 клиентов в top_nodes');
  const clusters = raw.clusters.map((c): Cluster => {
    if (!object(c) || !Number.isSafeInteger(c.cluster_id) || (c.cluster_id as number) < 0) throw new Error('Некорректный кластер');
    const count = amount(c.n_nodes, 'n_nodes', true), seeds = amount(c.n_seed, 'n_seed', true), value = amount(c.sum_kzt_internal, 'sum_kzt_internal');
    if (count === null || seeds === null || value === null) throw new Error('Нет метрик кластера');
    return { id: String(c.cluster_id), count, seeds, amount: value, hypothesis: text(c.hypothesis, 'hypothesis') };
  });
  const clusterIds = new Set(clusters.map(c => c.id));
  if (clusterIds.size !== clusters.length || nodes.some(n => !clusterIds.has(n.cluster))) throw new Error('Кластеры должны быть уникальны и покрывать всех клиентов');
  return { meta: { is_demo: isDemo, limitations: strings(meta.limitations, 'meta.limitations'), engine: String(meta.engine_version ?? meta.engine ?? 'Не указан') }, nodes, edges, top, clusters };
}
export function buildNeighbors(edges: Transfer[]): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!map.has(edge.source)) map.set(edge.source, new Set());
    if (!map.has(edge.target)) map.set(edge.target, new Set());
    map.get(edge.source)!.add(edge.target); map.get(edge.target)!.add(edge.source);
  }
  return map;
}
export function neighborhood(gid: string, neighbors: Map<string, Set<string>>, hops: number): Set<string> {
  const found = new Set([gid]); let frontier = [gid];
  for (let i = 0; i < hops; i++) {
    const next: string[] = [];
    for (const id of frontier) for (const adjacent of neighbors.get(id) ?? []) {
      if (!found.has(adjacent)) { found.add(adjacent); next.push(adjacent); }
    }
    frontier = next;
  }
  return found;
}
const warningLabels: Record<string, string> = {
  OBSERVED_SUBGRAPH_ONLY: 'Видна только часть переводов за выбранный период.',
  ROLE_IS_HYPOTHESIS: 'Роль — гипотеза для проверки.',
  OUTGOING_INCOMPLETE_AT_DEPTH_LIMIT: 'Граница обхода: дальнейшие исходящие переводы могут быть не видны. Это не доказывает, что клиент — конечный получатель.',
  SEED_INCOMING_INCOMPLETE: 'Для исходного клиента входящие переводы представлены неполно.',
  NO_OBSERVED_EDGES: 'В выгрузке нет связей этого клиента. Это не означает отсутствия переводов за её пределами.',
  SELF_TRANSFERS_EXCLUDED_FROM_ROLE_AND_PRIORITY: 'Переводы самому себе исключены из оценки роли и приоритета.',
  OBSERVED_OUTFLOW_EXCEEDS_INFLOW: 'Видимые исходящие превышают входящие; это не полный баланс счёта.',
};
export function clientLimitations(client: Client): string[] {
  const codes = new Set(client.warnings);
  if (client.depth === 4) codes.add('OUTGOING_INCOMPLETE_AT_DEPTH_LIMIT');
  if (client.is_seed) codes.add('SEED_INCOMING_INCOMPLETE');
  if (client.in_count === 0 && client.out_count === 0) codes.add('NO_OBSERVED_EDGES');
  return [...codes].filter(c => c !== 'ROLE_IS_HYPOTHESIS' && c !== 'OBSERVED_SUBGRAPH_ONLY')
    .map(c => warningLabels[c] ?? 'Дополнительное ограничение данных: ' + c);
}
export function clusterColor(cluster: string | null): string {
  if (cluster === null) return '#8795a6';
  let hash = 0; for (const char of cluster) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return 'hsl(' + ((hash * 137.508) % 360) + ', 48%, 47%)';
}
