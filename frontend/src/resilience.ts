export type ResilienceStrategy = 'priority' | 'volume';
export type ResilienceK = 1 | 3 | 5 | 10;
export const resilienceCounts: readonly ResilienceK[] = [1, 3, 5, 10];
export interface Scenario {
  strategy: 'baseline' | ResilienceStrategy;
  requested_k: number;
  removed_gids: string[];
  remaining_nodes: number;
  remaining_edges: number;
  weak_components: number;
  isolated_nodes: number;
  largest_component_nodes: number;
  largest_component_share_remaining: number;
  removed_edge_sum_kzt: number;
  removed_edge_sum_share: number;
}
export interface Resilience {
  schema_version: '1.0';
  connectivity: 'weak';
  scope: 'observed_graph';
  baseline: Scenario;
  scenarios: Scenario[];
}

const fail = (path: string, reason: string): never => {
  throw new Error(`Неверный формат «Устойчивость наблюдаемой сети» (${path}): ${reason}.`);
};
function object(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail(path, 'ожидается объект');
  return value as Record<string, unknown>;
}
function integer(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) return fail(path, 'ожидается целое неотрицательное число');
  return value;
}
function finite(value: unknown, path: string, share = false): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || (share && value > 1)) {
    return fail(path, share ? 'ожидается конечная доля от 0 до 1' : 'ожидается конечное неотрицательное число');
  }
  return value;
}
function parseScenario(raw: unknown, path: string, nodeIds: ReadonlySet<string>, edgeCount: number): Scenario {
  const value = object(raw, path);
  if (value.strategy !== 'baseline' && value.strategy !== 'priority' && value.strategy !== 'volume') return fail(`${path}.strategy`, 'неизвестный способ отбора');
  const requested_k = integer(value.requested_k, `${path}.requested_k`);
  if (!Array.isArray(value.removed_gids)) return fail(`${path}.removed_gids`, 'ожидается массив строк gid');
  const removed_gids: string[] = [], seen = new Set<string>();
  for (const gid of value.removed_gids) {
    if (typeof gid !== 'string' || !nodeIds.has(gid)) return fail(`${path}.removed_gids`, 'gid должен быть строкой существующего клиента');
    if (seen.has(gid)) return fail(`${path}.removed_gids`, 'клиент указан повторно');
    seen.add(gid); removed_gids.push(gid);
  }
  const scenario: Scenario = {
    strategy: value.strategy, requested_k, removed_gids,
    remaining_nodes: integer(value.remaining_nodes, `${path}.remaining_nodes`),
    remaining_edges: integer(value.remaining_edges, `${path}.remaining_edges`),
    weak_components: integer(value.weak_components, `${path}.weak_components`),
    isolated_nodes: integer(value.isolated_nodes, `${path}.isolated_nodes`),
    largest_component_nodes: integer(value.largest_component_nodes, `${path}.largest_component_nodes`),
    largest_component_share_remaining: finite(value.largest_component_share_remaining, `${path}.largest_component_share_remaining`, true),
    removed_edge_sum_kzt: finite(value.removed_edge_sum_kzt, `${path}.removed_edge_sum_kzt`),
    removed_edge_sum_share: finite(value.removed_edge_sum_share, `${path}.removed_edge_sum_share`, true),
  };
  if (removed_gids.length !== Math.min(requested_k, nodeIds.size)) return fail(path, 'число исключённых клиентов не соответствует N и размеру исходного графа');
  if (scenario.remaining_nodes !== nodeIds.size - removed_gids.length) return fail(path, 'число оставшихся клиентов не согласовано с исключёнными');
  if (scenario.remaining_edges > edgeCount) return fail(path, 'оставшихся связей больше, чем в исходном графе');
  const { remaining_nodes: nodes, largest_component_nodes: largest, weak_components: components, isolated_nodes: isolated } = scenario;
  if (nodes === 0) {
    if (scenario.remaining_edges !== 0 || components !== 0 || isolated !== 0 || largest !== 0) return fail(path, 'у пустой модели связи, компоненты и изолированные клиенты должны быть равны нулю');
  } else {
    if (largest < 1 || largest > nodes || components < 1 || components > nodes - largest + 1 || isolated > components) {
      return fail(path, 'размеры компонент и число изолированных клиентов не согласованы');
    }
    if ((largest === 1 && isolated !== nodes) || (largest > 1 && isolated > nodes - largest)) return fail(path, 'число изолированных клиентов не согласовано с крупнейшей компонентой');
  }
  const expectedShare = nodes === 0 ? 0 : largest / nodes;
  if (Math.abs(scenario.largest_component_share_remaining - expectedShare) > 1e-8) return fail(path, 'доля крупнейшей компоненты не согласована с числом оставшихся клиентов');
  return scenario;
}

/** Validate prepared results; never recompute graph connectivity or choose removed clients. */
export function parseResilience(raw: unknown, nodeIds: ReadonlySet<string>, edgeCount: number): Resilience | undefined {
  if (raw === undefined) return undefined;
  const value = object(raw, 'meta.resilience');
  if (value.schema_version !== '1.0') return fail('schema_version', 'ожидается версия 1.0');
  if (value.connectivity !== 'weak') return fail('connectivity', 'ожидается weak');
  if (value.scope !== 'observed_graph') return fail('scope', 'ожидается observed_graph');
  const baseline = parseScenario(value.baseline, 'baseline', nodeIds, edgeCount);
  if (baseline.strategy !== 'baseline' || baseline.requested_k !== 0 || baseline.removed_gids.length !== 0 || baseline.remaining_edges !== edgeCount || baseline.removed_edge_sum_kzt !== 0 || baseline.removed_edge_sum_share !== 0) {
    return fail('baseline', 'исходная модель должна описывать полный граф без исключений');
  }
  if (!Array.isArray(value.scenarios) || value.scenarios.length !== 8) return fail('scenarios', 'ожидаются все 8 сочетаний двух способов и N=1/3/5/10');
  const scenarios = value.scenarios.map((scenario, index) => parseScenario(scenario, `scenarios[${index}]`, nodeIds, edgeCount));
  const combinations = new Set<string>();
  for (const scenario of scenarios) {
    if (scenario.strategy === 'baseline' || !resilienceCounts.includes(scenario.requested_k as ResilienceK)) return fail('scenarios', 'допустимы только priority/volume и N=1/3/5/10');
    const key = `${scenario.strategy}:${scenario.requested_k}`;
    if (combinations.has(key)) return fail('scenarios', 'сочетание способа и N повторяется');
    combinations.add(key);
    if (scenario.largest_component_nodes > baseline.largest_component_nodes) return fail('scenarios', 'крупнейшая компонента после исключения не может вырасти');
    if (nodeIds.size === 0 && (scenario.removed_edge_sum_kzt !== 0 || scenario.removed_edge_sum_share !== 0)) return fail('scenarios', 'у пустого исходного графа нет исключённого оборота');
  }
  return { schema_version: '1.0', connectivity: 'weak', scope: 'observed_graph', baseline, scenarios };
}

export function resilienceScenario(resilience: Resilience, strategy: ResilienceStrategy, count: ResilienceK): Scenario {
  const scenario = resilience.scenarios.find(item => item.strategy === strategy && item.requested_k === count);
  if (!scenario) return fail('scenarios', 'отсутствует выбранное сочетание способа и N');
  return scenario;
}
