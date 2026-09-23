#!/usr/bin/env python3
"""Verify an existing, transferable pipeline bundle without recalculating it."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

from hackalem.protocol import strict_json, validate_result

PUBLIC_FILES = ('graph.json', 'nodes_roles.csv', 'clusters.csv', 'top_nodes.csv',
                'validation.json', 'run_manifest.json')
PROOF_FILES = ('input.json', 'result.json')
HASHED_FILES = (*PUBLIC_FILES[:-1], *PROOF_FILES)
CSV_COLUMNS = {
    'nodes_roles.csv': ['gid', 'role', 'role_score', 'cluster_id', 'priority_score', 'evidence'],
    'clusters.csv': ['cluster_id', 'n_nodes', 'n_seed', 'sum_kzt_internal', 'top_gids', 'hypothesis'],
    'top_nodes.csv': ['rank', 'gid', 'role', 'priority_score', 'why'],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index(rows, key, label):
    indexed = {row[key]: row for row in rows}
    require(len(indexed) == len(rows), f'{label}: duplicate {key}')
    return indexed


def same_number(a, b):
    try:
        return math.isfinite(float(a)) and math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
    except (ValueError, TypeError):
        return False


def same_integer(text, expected):
    """CSV integer fields must be exact decimal integers, never float approximations."""
    return type(expected) is int and isinstance(text, str) and text == str(expected)


def verify_bundle(out: Path, *, data: Path | None = None, core: Path | None = None,
                  allow_demo=False, base_url=None):
    """Require all six deliverables plus input/result provenance from the same run."""
    for name in (*PUBLIC_FILES, *PROOF_FILES):
        require((out/name).is_file(), f'missing bundle file: {name}')
    manifest = strict_json(out/'run_manifest.json')
    require(manifest.get('schema_version') == '1.0' and manifest.get('status') == 'complete',
            'manifest must describe a completed v1 run')
    def valid_digest(value):
        return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    for name in ('nodes.parquet', 'edges.parquet', 'transactions.parquet'):
        require(valid_digest(manifest.get('source_sha256', {}).get(name)), f'manifest lacks a valid source hash: {name}')
    if manifest.get('demo') is False:
        require(valid_digest(manifest.get('engine_sha256')), 'manifest lacks a valid C++ engine hash')
    hashes = manifest.get('artifact_sha256', {})
    require(set(HASHED_FILES) <= set(hashes), 'manifest lacks required artifact hashes (including validation.json)')
    for name, digest in hashes.items():
        require(isinstance(name, str) and Path(name).name == name and '/' not in name and '\\' not in name,
                'manifest artifact must be a plain file name')
        require((out/name).is_file() and sha256(out/name) == digest, f'artifact checksum mismatch: {name}')
    payload, result, graph, validation = [strict_json(out/name)
        for name in ('input.json', 'result.json', 'graph.json', 'validation.json')]
    demo = manifest.get('demo')
    require(type(demo) is bool, 'manifest.demo must be boolean')
    require(allow_demo or not demo, 'real C++ bundle required, got Python demo')
    require(graph.get('schema_version') == '1.0' and graph['meta'].get('is_demo') is demo
            and graph['meta'].get('demo') is demo, 'graph demo flags disagree with manifest')
    results = validate_result(result, payload, demo=demo)
    sources = index(payload['nodes'], 'gid', 'input nodes')
    nodes = index(graph['nodes'], 'gid', 'graph nodes')
    require(set(nodes) == set(sources) == set(results), 'graph/input/result node coverage differs')
    for gid, node in nodes.items():
        require(('next_actions' in node) == ('next_actions' in results[gid]),
                f'graph node {gid}: next_actions presence differs from result')
        for key, value in {**sources[gid], **results[gid]}.items():
            require(key in node and node[key] == value, f'graph node {gid}: lost or changed field {key}')
    expected_edges = [{'id': e['src']+':'+e['dst'], **e} for e in payload['edges']]
    require(graph['edges'] == expected_edges, 'graph directed edges differ from input')
    require(validation.get('ok') is True and validation == payload['meta']['validation']
            and validation == graph['meta']['validation'], 'validation.json disagrees with this run')
    expected_counts = {
        'n_nodes': len(nodes), 'n_edges': len(graph['edges']),
        'n_transactions': sum(e['n_tx'] for e in graph['edges']),
        'n_seed': sum(n['is_seed'] for n in nodes.values()),
        'n_isolated': sum(n['flags']['isolated'] for n in nodes.values()),
        'n_isolated_seed': sum(n['flags']['isolated'] and n['is_seed'] for n in nodes.values()),
    }
    for key, count in expected_counts.items():
        require(validation.get(key) == count, f'validation count differs: {key}')
    require(same_number(validation.get('sum_kzt'), math.fsum(e['sum_kzt'] for e in graph['edges'])),
            'validation turnover differs')
    require(manifest.get('clustering') == graph['meta']['clustering'] == payload['meta']['clustering'],
            'clustering metadata differs')
    for key in ('nodes', 'edges', 'clusters', 'top_nodes'):
        require(manifest.get('counts', {}).get(key) == len(graph[key]), f'manifest count differs: {key}')
    if not demo:
        require(manifest.get('engine_version') == graph['meta'].get('engine_version') == result['engine_version'],
                'engine versions differ')
        require(manifest.get('engine_config') == graph['meta'].get('config') == result['meta'].get('config'),
                'effective engine configuration differs')
        require(graph['meta'].get('engine_meta') == result['meta'], 'engine metadata lost')
    rows = {}
    for name, columns in CSV_COLUMNS.items():
        with (out/name).open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            require(reader.fieldnames == columns, f'{name}: wrong CSV columns')
            rows[name] = list(reader)
    role_rows = index(rows['nodes_roles.csv'], 'gid', 'nodes_roles.csv')
    require(set(role_rows) == set(nodes), 'CSV node coverage differs')
    for gid, row in role_rows.items():
        node = nodes[gid]
        for key in ('role', 'evidence'):
            require(row[key] == node[key], f'nodes_roles.csv {gid}: {key} differs')
        for key in ('role_score', 'priority_score'):
            require(same_number(row[key], node[key]), f'nodes_roles.csv {gid}: {key} differs')
        require(same_integer(row['cluster_id'], node['cluster_id']),
                f'nodes_roles.csv {gid}: cluster_id must be the exact integer')
    ranked = sorted(nodes.values(), key=lambda n: (-n['priority_score'], int(n['gid'])))
    require(min(20, len(nodes)) <= len(graph['top_nodes']) <= len(nodes), 'top length is invalid')
    expected_top = [{'rank': i+1, **{k: n[k] for k in ('gid', 'role', 'priority_score', 'why')}}
                    for i, n in enumerate(ranked[:len(graph['top_nodes'])])]
    require(graph['top_nodes'] == expected_top, 'graph top differs from scores/numeric gid ordering')
    require(len(rows['top_nodes.csv']) == len(expected_top), 'top CSV length differs')
    for actual, expected in zip(rows['top_nodes.csv'], expected_top):
        require(all(same_integer(actual[k], v) if k == 'rank' else
                    same_number(actual[k], v) if k == 'priority_score' else actual[k] == v
                    for k, v in expected.items()), 'top CSV row differs')
    clusters = index(graph['clusters'], 'cluster_id', 'graph clusters')
    cluster_rows = index(rows['clusters.csv'], 'cluster_id', 'clusters.csv')
    require(set(clusters) == {n['cluster_id'] for n in nodes.values()} and
            set(cluster_rows) == {str(cid) for cid in clusters}, 'cluster coverage differs')
    for cid, cluster in clusters.items():
        hypothesis = cluster.get('hypothesis')
        require(isinstance(hypothesis, str) and bool(hypothesis.strip()),
                f'cluster {cid}: hypothesis must be nonempty text')
        members = [n for n in ranked if n['cluster_id'] == cid]
        internal = math.fsum(e['sum_kzt'] for e in graph['edges']
                             if nodes[e['src']]['cluster_id'] == cid == nodes[e['dst']]['cluster_id'])
        require(cluster['n_nodes'] == len(members) and cluster['n_seed'] == sum(n['is_seed'] for n in members)
                and same_number(cluster['sum_kzt_internal'], internal)
                and cluster['top_gids'] == [n['gid'] for n in members[:5]], f'cluster {cid}: incorrect summary')
        row = cluster_rows[str(cid)]
        require(same_integer(row['cluster_id'], cid)
                and all(same_integer(row[k], cluster[k]) for k in ('n_nodes', 'n_seed'))
                and same_number(row['sum_kzt_internal'], cluster['sum_kzt_internal'])
                and json.loads(row['top_gids']) == cluster['top_gids'] and row['hypothesis'] == cluster['hypothesis'],
                f'cluster {cid}: CSV differs')
    if data is not None:
        for name in ('nodes.parquet', 'edges.parquet', 'transactions.parquet'):
            require(sha256(data/name) == manifest.get('source_sha256', {}).get(name), f'source checksum differs: {name}')
    if core is not None:
        require(sha256(core) == manifest.get('engine_sha256'), 'engine binary checksum differs')
    urls = []
    if base_url:
        # Check the actual downloadable bytes, including JSON/CSV encoding.
        for name in PUBLIC_FILES:
            url = base_url.rstrip('/') + '/' + name
            with urlopen(url, timeout=15) as response:
                downloaded = response.read()
            require(downloaded == (out/name).read_bytes(), f'HTTP payload differs: {url}')
            urls.append(url)
    return {'status': 'passed', 'engine_version': manifest.get('engine_version'), 'is_demo': demo,
            'counts': manifest['counts'], 'manifest_sha256': sha256(out/'run_manifest.json'),
            'validated_artifact_count': len(hashes), 'source_hashes_checked': data is not None,
            'engine_hash_checked': core is not None, 'http_urls_checked': urls}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('frontend/public/data'))
    ap.add_argument('--data', type=Path)
    ap.add_argument('--core', type=Path)
    ap.add_argument('--allow-demo', action='store_true')
    ap.add_argument('--base-url', help='URL prefix ending in /data for an optional HTTP byte check')
    args = ap.parse_args()
    try:
        print(json.dumps(verify_bundle(args.out, data=args.data, core=args.core, allow_demo=args.allow_demo,
                                       base_url=args.base_url), ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        print(f'Bundle verification failed: {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
