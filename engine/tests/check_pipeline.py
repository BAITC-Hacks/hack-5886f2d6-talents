#!/usr/bin/env python3
"""Run the real Python -> C++ -> CSV/UI integration and verify its artifacts.

Usage: python engine/tests/check_pipeline.py path/to/engine [--out directory]
Uses the interpreter running this script for pipeline.py. Its Python dependencies
must already be installed. Verifies the canonical flat UI export plus preservation
of the complete C++ result and the executed binary's provenance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "TechTask" / "data(1)" / "data"
CSV_COLUMNS = {
    "nodes_roles.csv": ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"],
    "clusters.csv": ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"],
    "top_nodes.csv": ["rank", "gid", "role", "priority_score", "why"],
}
ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
REQUIRED_NODE_FIELDS = ("features", "role_candidates", "priority_breakdown", "warnings")
FLAT_METRICS = ("in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "pagerank",
                "pass_through", "seed_in_neighbors", "neighbor_clusters", "turnover_kzt")


def read_json(path):
    def nonfinite(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=nonfinite,
                      object_pairs_hook=pairs)


def metric(node, name):
    return node[name] if name in node else node["metrics"][name]


def indexed(rows, field, label):
    result = {}
    for row in rows:
        value = row[field]
        if value in result:
            raise ValueError(f"{label}: duplicate {field}={value}")
        result[value] = row
    return result


def score(value):
    number = float(value)
    return math.isfinite(number) and 0 <= number <= 1


def same_number(a, b):
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-12)


def verify(out, executable, executed_sha256):
    failures, warnings = [], []

    def check(condition, message):
        if not condition:
            failures.append(message)

    payload = read_json(out / "input.json")
    result = read_json(out / "result.json")
    graph = read_json(out / "graph.json")
    manifest = read_json(out / "run_manifest.json")
    sources = indexed(payload["nodes"], "gid", "input")
    results = indexed(result["nodes"], "gid", "result")
    graph_nodes = indexed(graph["nodes"], "gid", "graph")
    check(len(sources) == 2248, f"real dataset must have 2248 nodes, got {len(sources)}")
    check(len(payload["edges"]) == 3119, "real dataset must have 3119 directed edges")
    check(set(sources) == set(results) == set(graph_nodes), "input/result/graph gid sets differ")
    check(all(isinstance(gid, str) and str(int(gid)) == gid and -(2**63) <= int(gid) < 2**63
              for gid in sources), "input gid must be canonical int64 strings")
    check(result.get("schema_version") == "1.0", "unexpected result schema_version")
    check(bool(result.get("engine_version")), "result lacks engine_version")
    check(manifest.get("status") == "complete", "manifest does not report complete run")
    check(manifest.get("demo") is False, "manifest must mark C++ run demo=false")
    check(manifest.get("engine_sha256") == executed_sha256,
          "manifest engine checksum differs from executed binary")
    check(hashlib.sha256(executable.read_bytes()).hexdigest() == executed_sha256,
          "engine binary changed while integration check was running")
    check(manifest.get("engine_version") == result.get("engine_version"),
          "manifest engine_version differs from C++ result")
    expected_engine = "cpp-" + result.get("engine_version", "")
    check(manifest.get("engine") == expected_engine, "manifest engine label differs from C++ version")
    graph_meta = graph.get("meta", {})
    check(graph_meta.get("is_demo") is False, "graph must set meta.is_demo=false")
    check(graph_meta.get("engine_version") == result.get("engine_version"),
          "graph engine_version differs from C++ result")
    check(graph_meta.get("engine") == expected_engine, "graph engine label differs from C++ version")
    check(graph_meta.get("engine_meta") == result.get("meta"),
          "graph must preserve all C++ metadata in meta.engine_meta")

    isolated = {gid for gid, node in sources.items()
                if metric(node, "in_deg") == metric(node, "out_deg") == 0}
    check(len(isolated) == 19, f"real dataset must retain 19 isolates, got {len(isolated)}")
    check(all(sources[gid]["is_seed"] for gid in isolated), "all 19 real-data isolates must be seed")

    csv_rows = {}
    for name, columns in CSV_COLUMNS.items():
        with (out / name).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            check(reader.fieldnames == columns, f"{name}: unexpected columns {reader.fieldnames}")
            csv_rows[name] = list(reader)
    node_csv = indexed(csv_rows["nodes_roles.csv"], "gid", "nodes_roles.csv")
    check(set(node_csv) == set(sources), "nodes_roles.csv must include every input gid exactly once")
    for gid, source in sources.items():
        if gid not in results or gid not in graph_nodes or gid not in node_csv:
            continue
        node, ui, row = results[gid], graph_nodes[gid], node_csv[gid]
        check(node["role"] in ROLES, f"{gid}: invalid role")
        check(node.get("cluster_id") == source["cluster_id"], f"{gid}: C++ changed cluster_id")
        check(int(row["cluster_id"]) == ui["cluster_id"] == source["cluster_id"],
              f"{gid}: exported cluster_id differs")
        for field in FLAT_METRICS:
            check(field in ui and ui[field] == metric(source, field),
                  f"{gid}: graph must preserve flat input metric {field}")
        for field in ("depth", "is_seed", "truncated_by_depth", "flags"):
            check(field in ui and ui[field] == source[field],
                  f"{gid}: graph must preserve input field {field}")
        for field in ("role_score", "priority_score"):
            check(score(node[field]) and score(row[field]) and score(ui[field]),
                  f"{gid}: {field} outside [0,1]")
            check(same_number(node[field], row[field]) and same_number(node[field], ui[field]),
                  f"{gid}: {field} changed during export")
        for field in ("role", "evidence"):
            check(node[field] == row[field] == ui[field], f"{gid}: exported {field} differs")
        check(node["why"] == ui["why"], f"{gid}: exported why differs")
        for field in ("evidence", "why"):
            value = node[field]
            check(isinstance(value, str) and bool(value.strip()) and len(value) <= 200,
                  f"{gid}: {field} must be nonempty and <=200 characters")
        if source["depth"] == 4 or source["is_seed"]:
            check(node["role"] not in {"terminal", "transit"},
                  f"{gid}: terminal/transit forbidden at boundary or seed")
        if gid in isolated:
            check(node["role"] == "peripheral" and node["priority_score"] == 0,
                  f"{gid}: isolate must remain peripheral with zero priority")
        for field in REQUIRED_NODE_FIELDS:
            check(field in node and field in ui and node[field] == ui[field],
                  f"{gid}: graph must preserve required C++ {field}")
        if "next_actions" in node:
            check(ui.get("next_actions") == node["next_actions"],
                  f"{gid}: graph must preserve C++ next_actions")

    engine_config = result.get("meta", {}).get("config")
    check(isinstance(engine_config, dict), "C++ result must expose effective configuration")
    check(engine_config is not None and graph_meta.get("config") == engine_config,
          "graph must preserve effective C++ configuration in meta.config")
    check(engine_config is not None and manifest.get("engine_config") == engine_config,
          "manifest must preserve effective C++ configuration")

    expected_top = sorted(results.values(), key=lambda n: (-n["priority_score"], int(n["gid"])))[:20]
    expected_top_ids = [n["gid"] for n in expected_top]
    for label, rows in (("C++ top_nodes", result["top_nodes"]),
                        ("graph top_nodes", graph["top_nodes"]),
                        ("top_nodes.csv", csv_rows["top_nodes.csv"])):
        check([n["gid"] for n in rows] == expected_top_ids,
              f"{label}: top-20 differs from C++ scores with numeric gid tie-breaking")
        for rank, row in enumerate(rows, 1):
            node = results.get(row["gid"])
            check(int(row["rank"]) == rank, f"{label}: invalid rank")
            if node is not None:
                check(row["role"] == node["role"] and row["why"] == node["why"] and
                      same_number(row["priority_score"], node["priority_score"]),
                      f"{label}: row {rank} differs from C++ result")

    edge_fields = ("src", "dst", "sum_kzt", "n_tx")
    edge_signature = lambda rows: sorted(tuple(edge[k] for k in edge_fields) for edge in rows)
    check(edge_signature(payload["edges"]) == edge_signature(graph["edges"]),
          "graph directed edges differ from input")
    check(all(edge.get("id") == edge["src"] + ":" + edge["dst"] for edge in graph["edges"]),
          "graph edges must have exact id=src:dst")
    check(len({edge.get("id") for edge in graph["edges"]}) == len(graph["edges"]),
          "graph edge identifiers must be unique")
    clusters = indexed(graph["clusters"], "cluster_id", "graph clusters")
    cluster_csv = indexed(csv_rows["clusters.csv"], "cluster_id", "clusters.csv")
    check({str(k) for k in clusters} == set(cluster_csv), "cluster CSV/graph identifiers differ")
    check(set(clusters) == {n["cluster_id"] for n in sources.values()}, "cluster coverage differs")
    for cid, cluster in clusters.items():
        members = [n for n in results.values() if n["cluster_id"] == cid]
        check(cluster["n_nodes"] == len(members), f"cluster {cid}: incorrect n_nodes")
        check(cluster["n_seed"] == sum(sources[n["gid"]]["is_seed"] for n in members),
              f"cluster {cid}: incorrect n_seed")
        internal = math.fsum(e["sum_kzt"] for e in payload["edges"]
                             if sources[e["src"]]["cluster_id"] == cid == sources[e["dst"]]["cluster_id"])
        check(math.isclose(cluster["sum_kzt_internal"], internal, rel_tol=0, abs_tol=0.01),
              f"cluster {cid}: internal amount differs")
        leaders = sorted(members, key=lambda n: (-n["priority_score"], int(n["gid"])))[:5]
        check(cluster["top_gids"] == [n["gid"] for n in leaders], f"cluster {cid}: leaders differ")
        if str(cid) in cluster_csv:
            row = cluster_csv[str(cid)]
            check(int(row["n_nodes"]) == cluster["n_nodes"] and int(row["n_seed"]) == cluster["n_seed"]
                  and row["hypothesis"] == cluster["hypothesis"]
                  and json.loads(row["top_gids"]) == cluster["top_gids"]
                  and same_number(row["sum_kzt_internal"], cluster["sum_kzt_internal"]),
                  f"cluster {cid}: CSV and graph differ")

    hashes = manifest.get("artifact_sha256", {})
    required = {"input.json", "result.json", "graph.json", *CSV_COLUMNS}
    check(required <= set(hashes), "manifest lacks hashes of required artifacts")
    for name, expected in hashes.items():
        check(Path(name).name == name, f"manifest artifact must be a file name: {name}")
        if Path(name).name != name:
            continue
        path = out / name
        check(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
              f"manifest artifact checksum mismatch: {name}")
    source_hashes = manifest.get("source_sha256", {})
    for name in ("nodes.parquet", "edges.parquet", "transactions.parquet"):
        check(source_hashes.get(name) == hashlib.sha256((DATA / name).read_bytes()).hexdigest(),
              f"manifest source checksum mismatch: {name}")
    for name in ("nodes", "edges", "clusters", "top_nodes"):
        check(manifest.get("counts", {}).get(name) == len(graph[name]), f"manifest count mismatch: {name}")
    return {"status": "passed" if not failures else "failed", "n_nodes": len(sources),
            "n_edges": len(payload["edges"]), "n_isolated": len(isolated),
            "n_clusters": len(clusters), "engine_version": result.get("engine_version"),
            "failures": failures, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "engine" / "test-output" / "pipeline-integration")
    args = parser.parse_args()
    executable, out = args.engine.resolve(), args.out.resolve()
    if not executable.is_file():
        parser.error(f"engine executable not found: {executable}")
    command = [sys.executable, str(ROOT / "pipeline.py"), "--data", str(DATA),
               "--core", str(executable), "--out", str(out)]
    try:
        executed_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
        started = time.perf_counter()
        process = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8",
                                 errors="replace", timeout=310)
        elapsed_wall_seconds = time.perf_counter() - started
        if process.returncode:
            print(process.stdout, end="")
            print(process.stderr, end="", file=sys.stderr)
            return process.returncode
        report = verify(out, executable, executed_sha256)
        report["elapsed_wall_seconds"] = round(elapsed_wall_seconds, 3)
    except Exception as error:
        print(f"integration check: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    (out / "integration-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
