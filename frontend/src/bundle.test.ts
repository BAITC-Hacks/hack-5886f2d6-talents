import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { csvFiles, loadGraphBundle } from './bundle';

const sha256 = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');
function fixture() {
  const files: Record<string, string> = {};
  for (const name of ['graph.json', ...csvFiles]) files[name] = readFileSync(new URL('../../examples/' + name, import.meta.url), 'utf8');
  const graph = JSON.parse(files['graph.json']);
  files['run_manifest.json'] = JSON.stringify({
    schema_version: '1.0', status: 'complete', demo: graph.meta.is_demo,
    counts: { nodes: graph.nodes.length, edges: graph.edges.length, clusters: graph.clusters.length, top_nodes: graph.top_nodes.length },
    artifact_sha256: Object.fromEntries(Object.entries(files).map(([name, content]) => [name, sha256(content)])),
  });
  return files;
}
function serve(files: Record<string, string>, calls: string[] = []): typeof fetch {
  return async (url, options) => {
    assert.equal(options?.cache, 'no-store');
    assert.ok(options?.signal instanceof AbortSignal);
    const name = String(url).split('/').at(-1)!;
    calls.push(name);
    return Object.hasOwn(files, name) ? new Response(files[name]) : new Response('', { status: 404 });
  };
}

test('retains exact verified CSV bytes even after the server changes to a new run', async () => {
  const files = fixture(), calls: string[] = [];
  const expected = files['nodes_roles.csv'];
  const bundle = await loadGraphBundle('/data/', new AbortController().signal, serve(files, calls));
  assert.equal(bundle.graph.nodes.length, JSON.parse(files['graph.json']).nodes.length);
  files['nodes_roles.csv'] += 'new run\n';
  const download = new Blob([bundle.exports.find(file => file.name === 'nodes_roles.csv')!.bytes], { type: 'text/csv' });
  assert.equal(await download.text(), expected);
  assert.equal(calls.filter(name => name === 'run_manifest.json').length, 2);
  for (const name of ['graph.json', ...csvFiles]) assert.equal(calls.filter(called => called === name).length, 1);
});

test('rejects changed CSV rows although the required header still matches', async () => {
  const files = fixture();
  files['nodes_roles.csv'] += 'corrupt or stale rows\n';
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, serve(files)), /не согласованы \(nodes_roles\.csv\)/);
});

test('rejects a changed manifest even when every downloaded artifact matches the first manifest', async () => {
  const files = fixture(), request = serve(files); let manifests = 0;
  const changing: typeof fetch = async (url, options) => {
    if (String(url).endsWith('run_manifest.json') && ++manifests === 2) {
      files['run_manifest.json'] = JSON.stringify({ ...JSON.parse(files['run_manifest.json']), next_run: true });
    }
    return request(url, options);
  };
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, changing), /обновились во время загрузки/);
});

test('rejects missing CSV and missing artifact hashes rather than displaying a partial bundle', async () => {
  const missing = fixture(); delete missing['top_nodes.csv'];
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, serve(missing)), /top_nodes\.csv недоступен: HTTP 404/);
  const incomplete = fixture(), manifest = JSON.parse(incomplete['run_manifest.json']);
  delete manifest.artifact_sha256['clusters.csv']; incomplete['run_manifest.json'] = JSON.stringify(manifest);
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, serve(incomplete)), /нет SHA-256 для clusters\.csv/);
});

test('rejects invalid CSV schema even when its hash matches the manifest', async () => {
  const files = fixture(), manifest = JSON.parse(files['run_manifest.json']);
  files['clusters.csv'] = 'wrong,header\n';
  manifest.artifact_sha256['clusters.csv'] = sha256(files['clusters.csv']);
  files['run_manifest.json'] = JSON.stringify(manifest);
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, serve(files)), /заголовок clusters\.csv/);
});

test('rejects contradictory run metadata and cancelled loads', async () => {
  const files = fixture(), manifest = JSON.parse(files['run_manifest.json']);
  manifest.demo = !manifest.demo; files['run_manifest.json'] = JSON.stringify(manifest);
  await assert.rejects(loadGraphBundle('/data/', new AbortController().signal, serve(files)), /сведения о расчёте/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(loadGraphBundle('/data/', controller.signal, serve(fixture())), { name: 'AbortError' });
});

test('accepts the checked-in production delivery with its original manifest hashes', async () => {
  const files = Object.fromEntries(['run_manifest.json', 'graph.json', ...csvFiles].map(name =>
    [name, readFileSync(new URL('../public/data/' + name, import.meta.url), 'utf8')]));
  const bundle = await loadGraphBundle('/data/', new AbortController().signal, serve(files));
  assert.equal(bundle.graph.meta.is_demo, false);
  assert.equal(bundle.graph.nodes.length, JSON.parse(files['run_manifest.json']).counts.nodes);
  assert.deepEqual(bundle.exports.map(file => file.name), [...csvFiles]);
});
