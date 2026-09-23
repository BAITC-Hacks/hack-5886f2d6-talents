import { parseGraph, type GraphData } from './data';

export const csvFiles = ['nodes_roles.csv', 'clusters.csv', 'top_nodes.csv'] as const;
const artifactFiles = ['graph.json', ...csvFiles] as const;
const csvHeaders: Record<typeof csvFiles[number], string> = {
  'nodes_roles.csv': 'gid,role,role_score,cluster_id,priority_score,evidence',
  'clusters.csv': 'cluster_id,n_nodes,n_seed,sum_kzt_internal,top_gids,hypothesis',
  'top_nodes.csv': 'rank,gid,role,priority_score,why',
};
type Obj = Record<string, unknown>;
const object = (value: unknown): value is Obj => !!value && typeof value === 'object' && !Array.isArray(value);
const decode = (bytes: ArrayBuffer) => new TextDecoder('utf-8', { fatal: true }).decode(bytes);
const mismatch = (name: string) => new Error('Файлы расчёта не согласованы (' + name + '). Завершите пересчёт и повторите загрузку.');

export interface GraphBundle {
  graph: GraphData;
  exports: { name: typeof csvFiles[number]; bytes: ArrayBuffer }[];
}

// Keep the verified bytes: downloading the URL again could return a newer run.
export async function loadGraphBundle(root: string, signal: AbortSignal, fetchFile: typeof fetch = fetch): Promise<GraphBundle> {
  async function read(name: string): Promise<ArrayBuffer> {
    const response = await fetchFile(root + name, { signal, cache: 'no-store' });
    if (!response.ok) throw new Error(name + ' недоступен: HTTP ' + response.status + '. Повторите загрузку после завершения расчёта.');
    return response.arrayBuffer();
  }
  const before = await read('run_manifest.json');
  const manifest: unknown = JSON.parse(decode(before));
  if (!object(manifest) || manifest.schema_version !== '1.0' || manifest.status !== 'complete'
    || typeof manifest.demo !== 'boolean' || !object(manifest.artifact_sha256) || !object(manifest.counts)) {
    throw new Error('Некорректный run_manifest.json. Нужен завершённый комплект расчёта формата 1.0.');
  }
  const hashes = manifest.artifact_sha256;
  const counts = manifest.counts;
  for (const name of artifactFiles) {
    if (typeof hashes[name] !== 'string' || !/^[a-f0-9]{64}$/i.test(hashes[name])) throw mismatch('нет SHA-256 для ' + name);
  }
  if (!globalThis.crypto?.subtle) throw new Error('Для проверки файлов откройте приложение через localhost или HTTPS.');
  const files = await Promise.all(artifactFiles.map(async name => {
    const bytes = await read(name);
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const actual = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
    if (actual !== (hashes[name] as string).toLowerCase()) throw mismatch(name);
    return { name, bytes };
  }));
  const after = await read('run_manifest.json');
  const first = new Uint8Array(before), last = new Uint8Array(after);
  if (first.length !== last.length || first.some((value, index) => value !== last[index])) {
    throw new Error('Данные обновились во время загрузки. Нажмите «Повторить загрузку», чтобы открыть один расчёт.');
  }
  signal.throwIfAborted();
  const graph = parseGraph(JSON.parse(decode(files[0].bytes)));
  const expectedCounts = { nodes: graph.nodes.length, edges: graph.edges.length, clusters: graph.clusters.length, top_nodes: graph.top.length };
  if (manifest.demo !== graph.meta.is_demo || Object.entries(expectedCounts).some(([key, value]) => counts[key] !== value)) {
    throw mismatch('graph.json и сведения о расчёте');
  }
  const exports = csvFiles.map(name => {
    const bytes = files.find(file => file.name === name)!.bytes;
    const header = decode(bytes).replace(/^\uFEFF/, '').split(/\r?\n/)[0].split(',').map(value => value.replace(/^"|"$/g, '')).join(',');
    if (header !== csvHeaders[name]) throw mismatch('заголовок ' + name);
    return { name, bytes };
  });
  return { graph, exports };
}
