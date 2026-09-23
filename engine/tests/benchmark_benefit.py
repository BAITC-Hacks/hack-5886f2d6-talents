#!/usr/bin/env python3
"""Independent, reproducible structural comparison; not an accuracy benchmark.

Run from the repository root. Uses only the Python standard library and the
observed graph, with no labels, gid-specific answers, or network requests.
"""
import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
KS = (1, 3, 5, 10)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(actual, expected, path="meta.resilience"):
    """Check complete engine payload against independently rebuilt values."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(f"{path}: different object keys")
        for key, value in expected.items():
            compare(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{path}: different list length")
        for i, (a, e) in enumerate(zip(actual, expected)):
            compare(a, e, f"{path}[{i}]")
    elif isinstance(expected, float):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            raise AssertionError(f"{path}: expected a number")
        if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise AssertionError(f"{path}: {actual!r} != {expected!r}")
    elif type(actual) is not type(expected) or actual != expected:
        raise AssertionError(f"{path}: {actual!r} != {expected!r}")


def evaluate(source, result):
    nodes = {n["gid"]: n for n in source["nodes"]}
    answers = {n["gid"]: n for n in result["nodes"]}
    if len(nodes) != len(source["nodes"]) or len(answers) != len(result["nodes"]):
        raise ValueError("Duplicate node gid")
    if set(nodes) != set(answers):
        raise ValueError("Input and result node gids differ")
    if any(not isinstance(g, str) or str(int(g)) != g for g in nodes):
        raise ValueError("Expected canonical string gids")

    edges = source["edges"]
    weak = {g: set() for g in nodes}
    outgoing = {g: set() for g in nodes}
    incoming_amount = {g: [] for g in nodes}
    outgoing_amount = {g: [] for g in nodes}
    for e in edges:
        a, b, amount = e["src"], e["dst"], e["sum_kzt"]
        if a not in nodes or b not in nodes or not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid edge")
        weak[a].add(b)
        weak[b].add(a)
        outgoing[a].add(b)
        if a != b:
            outgoing_amount[a].append(amount)
            incoming_amount[b].append(amount)
    total_amount = math.fsum(e["sum_kzt"] for e in edges)
    volume = {g: max(math.fsum(incoming_amount[g]), math.fsum(outgoing_amount[g])) for g in nodes}
    rankings = {
        "priority": sorted(nodes, key=lambda g: (-answers[g]["priority_score"], int(g))),
        "volume": sorted(nodes, key=lambda g: (-volume[g], int(g))),
    }

    def scenario(strategy, k, ranking):
        removed_gids = ranking[:min(k, len(nodes))]
        removed = set(removed_gids)
        remaining = set(nodes) - removed
        unseen = set(remaining)
        sizes = []
        while unseen:
            start = unseen.pop()
            queue = deque([start])
            size = 0
            while queue:
                g = queue.popleft()
                size += 1
                for other in weak[g]:
                    if other in unseen:
                        unseen.remove(other)
                        queue.append(other)
            sizes.append(size)
        retained_edges = [e for e in edges if e["src"] not in removed and e["dst"] not in removed]
        removed_amount = math.fsum(e["sum_kzt"] for e in edges if e["src"] in removed or e["dst"] in removed)
        largest = max(sizes, default=0)
        return {
            "strategy": strategy, "requested_k": k, "removed_gids": removed_gids,
            "remaining_nodes": len(remaining), "remaining_edges": len(retained_edges),
            "weak_components": len(sizes), "isolated_nodes": sizes.count(1),
            "largest_component_nodes": largest,
            "largest_component_share_remaining": largest / len(remaining) if remaining else 0.0,
            "removed_edge_sum_kzt": removed_amount,
            "removed_edge_sum_share": removed_amount / total_amount if total_amount else 0.0,
        }

    baseline = scenario("baseline", 0, [])
    scenarios = [scenario(strategy, k, rankings[strategy]) for strategy in ("priority", "volume") for k in KS]
    oracle = {
        "schema_version": "1.0", "connectivity": "weak", "scope": "observed_graph",
        "baseline": baseline, "scenarios": scenarios,
    }

    # A seed covers a selected client if a positive-length directed path reaches
    # that client. The seed itself is excluded even if a directed cycle returns.
    seeds = [g for g, n in nodes.items() if n.get("is_seed", False)]
    reached_by = {g: set() for g in nodes}
    for seed in seeds:
        visited = {seed}
        queue = deque([seed])
        while queue:
            for other in outgoing[queue.popleft()]:
                if other not in visited:
                    visited.add(other)
                    queue.append(other)
        for g in visited - {seed}:
            reached_by[g].add(seed)

    comparisons = []
    for s in scenarios:
        chosen = set(s["removed_gids"])
        covered_seeds = set().union(*(reached_by[g] for g in chosen)) if chosen else set()
        comparisons.append({
            "strategy": s["strategy"], "requested_k": s["requested_k"], "actual_k": len(chosen),
            "largest_component_nodes": s["largest_component_nodes"],
            "largest_component_reduction_nodes": baseline["largest_component_nodes"] - s["largest_component_nodes"],
            "removed_directed_edges": len(edges) - s["remaining_edges"],
            "incident_observed_sum_kzt": s["removed_edge_sum_kzt"],
            "incident_observed_sum_share": s["removed_edge_sum_share"],
            "upstream_distinct_seeds": len(covered_seeds),
            "selected_cluster_count": len({nodes[g]["cluster_id"] for g in chosen}),
        })

    engine_resilience = result.get("meta", {}).get("resilience")
    status = "not_present_in_result"
    if engine_resilience is not None:
        compare(engine_resilience, oracle)
        status = "matched_all_9_scenarios"
    return {
        "scope": "observed_graph_only", "connectivity": "weak",
        "node_count": len(nodes), "edge_count": len(edges), "seed_count": len(seeds),
        "observed_edge_sum_kzt": total_amount,
        "engine_version": result.get("engine_version"), "engine_resilience_check": status,
        "oracle_resilience": oracle, "comparisons": comparisons,
        "limitations": [
            "No role labels or fraud labels: this is not precision, recall, or fraud effectiveness.",
            "Fixed rankings and observed incomplete graph; no adaptive rescoring or reclustering.",
            "Incident observed amount is historical volume, not prevented loss.",
            "Seed coverage is overlapping reachability, not a count of independent cases.",
            "Component fragmentation does not establish disruption of actual activity.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "frontend/public/data/input.json")
    parser.add_argument("--result", type=Path, default=ROOT / "frontend/public/data/result.json")
    parser.add_argument("--out", type=Path, default=ROOT / "engine/test-output/benefit.json")
    parser.add_argument("--engine", type=Path, help="Generate a fresh result using this executable")
    parser.add_argument("--runs", type=int, default=5, help="Engine timing runs, including process startup (default: 5)")
    parser.add_argument("--require-engine-resilience", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    source = read_json(args.input)
    timing = None
    if args.engine:
        durations = []
        with tempfile.TemporaryDirectory(prefix="money_graph_benefit_") as folder:
            output = Path(folder) / "result.json"
            for _ in range(args.runs):
                started = time.perf_counter()
                subprocess.run([str(args.engine.resolve()), str(args.input.resolve()), str(output)], check=True, capture_output=True, text=True)
                durations.append(time.perf_counter() - started)
            result = read_json(output)
            result_hash = sha256(output)
        timing = {"runs": args.runs, "includes": "process startup, JSON I/O and all C++ analysis",
                  "min_seconds": min(durations), "median_seconds": statistics.median(durations),
                  "max_seconds": max(durations)}
    else:
        result = read_json(args.result)
        result_hash = sha256(args.result)
    report = evaluate(source, result)
    report["input_sha256"] = sha256(args.input)
    report["result_sha256"] = result_hash
    if timing is not None:
        report["local_engine_timing"] = timing
    if args.require_engine_resilience and report["engine_resilience_check"] != "matched_all_9_scenarios":
        raise AssertionError("Result has no engine resilience; use a C++ 1.3 result or --engine")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{report['node_count']} nodes, {report['edge_count']} edges; engine oracle: {report['engine_resilience_check']}")
    print("strategy k LCC removed_edges observed_KZT seed_coverage selected_clusters")
    for row in report["comparisons"]:
        print(f"{row['strategy']:8} {row['actual_k']:2} {row['largest_component_nodes']:4} "
              f"{row['removed_directed_edges']:4} {row['incident_observed_sum_kzt']:14.2f} "
              f"{row['upstream_distinct_seeds']:3} {row['selected_cluster_count']:2}")
    if timing:
        print(f"Local C++ median: {timing['median_seconds']:.6f}s ({args.runs} runs, includes startup and I/O)")
    print(f"Report: {args.out}")


if __name__ == "__main__":
    main()
