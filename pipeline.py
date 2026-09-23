#!/usr/bin/env python3
"""One command: raw Parquet -> features/Louvain -> external core -> exports."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def worker(args):
    # Imports belong inside the worker so dependency startup is timed too.
    import networkx as nx
    from hackalem.data import load, sanity_check, build_graph, basic_features, cluster_graph
    from hackalem.protocol import make_input, write_json, strict_json, validate_result
    from hackalem.export import export_outputs

    started = time.monotonic()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    edges, nodes, tx = load(args.data)
    validation = sanity_check(edges, nodes, tx)
    G = build_graph(edges, nodes)
    validation['n_weak_components_with_isolates'] = nx.number_weakly_connected_components(G)
    validation['n_self_loops'] = nx.number_of_selfloops(G)
    features = basic_features(G, nodes)
    mapping, clustering = cluster_graph(G, args.seed, args.resolution)
    features['cluster_id'] = features.gid.map(mapping).astype('int64')
    features['neighbor_clusters'] = features.gid.map(
        lambda gid: len({mapping[v] for v in set(G.predecessors(gid)) | set(G.successors(gid))}))
    payload = make_input(G, features, clustering, validation)
    if args.prepare_only:
        write_json(out / 'input.json', payload)
        write_json(out / 'validation.json', validation)
        print(json.dumps({'status': 'prepared', 'out': str(out), **validation}, ensure_ascii=True))
        return
    command = [sys.executable, str(ROOT / 'demo_core.py')] if args.demo else [str(args.core.resolve())]
    # Unique staging prevents stale results and leaves previous exports intact on failure.
    with tempfile.TemporaryDirectory(prefix='.pipeline-', dir=out) as staging:
        stage = Path(staging)
        write_json(stage / 'input.json', payload)
        remaining = args.deadline - time.time()
        if remaining <= 0:
            raise TimeoutError('pipeline time budget exhausted before core')
        core_cmd = [*command, '--input', str(stage/'input.json'), '--output', str(stage/'result.json')]
        with (stage/'core.stdout.log').open('w', encoding='utf-8') as stdout, (stage/'core.stderr.log').open('w', encoding='utf-8') as stderr:
            process = subprocess.Popen(core_cmd, cwd=ROOT, stdout=stdout, stderr=stderr, shell=False)
            try:
                code = process.wait(timeout=min(args.core_timeout, remaining))
            except subprocess.TimeoutExpired:
                kill_tree(process)
                raise TimeoutError('core timed out') from None
        if code:
            detail = (stage/'core.stderr.log').read_text(encoding='utf-8', errors='replace')[-4000:]
            raise RuntimeError(f'core exited with code {code}: {detail}')
        if not (stage/'result.json').is_file():
            raise ValueError('core returned success without result.json')
        result = strict_json(stage/'result.json')
        validated = validate_result(result, payload)
        graph = export_outputs(payload, validated, stage, result['engine'], args.demo, args.top)
        write_json(stage/'validation.json', validation)
        manifest = {
            'schema_version': '1.0', 'status': 'complete', 'demo': args.demo, 'engine': result['engine'],
            'elapsed_worker_seconds': round(time.monotonic()-started, 3),
            'counts': {k: len(graph[k]) for k in ('nodes', 'edges', 'clusters', 'top_nodes')},
            'clustering': clustering, 'python': sys.version.split()[0],
            'dependencies': {m: importlib.metadata.version(m) for m in ('pandas', 'numpy', 'pyarrow', 'networkx', 'scipy')},
            'source_sha256': {name: hashlib.sha256((args.data/name).read_bytes()).hexdigest()
                              for name in ('nodes.parquet', 'edges.parquet', 'transactions.parquet')},
        }
        manifest['artifact_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in stage.iterdir() if p.suffix in ('.csv', '.json')}
        write_json(stage/'run_manifest.json', manifest)
        # Publish manifest last: consumers can verify hashes before accepting a bundle.
        for path in sorted(stage.iterdir(), key=lambda p: (p.name == 'run_manifest.json', p.name)):
            os.replace(path, out/path.name)
        print(json.dumps({'status': 'complete', 'out': str(out), **manifest['counts'],
                          'demo': args.demo, 'seconds': manifest['elapsed_worker_seconds']}, ensure_ascii=True))


def kill_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False)
    else:
        import signal
        # The supervisor starts a process group containing worker and core.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=ROOT/'TechTask'/'data(1)'/'data')
    ap.add_argument('--out', type=Path, default=ROOT/'out')
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument('--core', type=Path, help='C++ executable implementing CONTRACT.md')
    modes.add_argument('--demo', action='store_true', help='explicit Python demo, not the C++ engine')
    modes.add_argument('--prepare-only', action='store_true', help='validate data and write input.json for Arthur')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--resolution', type=float, default=1.0)
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--timeout', type=float, default=300, help='whole-run time limit in seconds, maximum 300')
    ap.add_argument('--core-timeout', type=float, default=120)
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--deadline', type=float, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    import math
    for k in ('timeout', 'core_timeout', 'resolution'):
        if not math.isfinite(getattr(args, k)) or getattr(args, k) <= 0:
            ap.error(f'--{k.replace("_", "-")} must be finite and positive')
    if args.timeout > 300:
        ap.error('--timeout cannot exceed 300 seconds')
    if args.top < 20:
        ap.error('--top must be >=20')
    if args.core and not args.core.is_file():
        ap.error(f'core executable not found: {args.core}')
    return args


def main():
    args = parse_args()
    if args.worker:
        try:
            worker(args)
            return 0
        except Exception as exc:
            print(f'Pipeline failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
    start = time.monotonic()
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker', '--deadline', str(time.time()+args.timeout)]
    process = subprocess.Popen(command, start_new_session=os.name != 'nt')
    try:
        code = process.wait(timeout=args.timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        kill_tree(process)
        print('Pipeline interrupted or exceeded its time budget; no new successful run is claimed.', file=sys.stderr)
        return 124
    print(f'Total runtime: {time.monotonic()-start:.3f}s', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
