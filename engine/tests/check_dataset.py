"""Integration check using the organizer's starter; not the production pipeline.

Produces input/result JSON and a validation report for Arman's integration.
Usage: python engine/tests/check_dataset.py engine/build/engine.exe
"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import networkx as nx
import numpy as np
import pandas as pd


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", type=Path)
    parser.add_argument("--data", type=Path, default=root / "TechTask/data(1)/data")
    parser.add_argument("--out", type=Path, default=root / "engine/test-output")
    args = parser.parse_args()
    started = time.perf_counter()
    spec = importlib.util.spec_from_file_location("organizer_starter", root / "TechTask/starter(1)/starter/starter.py")
    starter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(starter)
    edges, nodes, transactions = starter.load(args.data)
    assert nodes.gid.is_unique
    assert not edges.duplicated(["src", "dst"]).any()
    aggregated = transactions.groupby(["src", "dst"]).agg(
        actual_sum=("sum_kzt", "sum"), actual_count=("sum_kzt", "size")).reset_index()
    matched = edges.merge(aggregated, on=["src", "dst"], how="outer", validate="one_to_one", indicator=True)
    assert (matched["_merge"] == "both").all()
    assert np.allclose(matched.sum_kzt, matched.actual_sum, rtol=1e-9, atol=0.01)
    assert (matched.n_tx == matched.actual_count).all()

    graph = starter.build_graph(edges)
    graph.add_nodes_from(int(gid) for gid in nodes.gid)
    features = starter.basic_features(graph, nodes)
    # Sum opposite directions explicitly; DiGraph.to_undirected() would overwrite a weight.
    undirected = nx.Graph()
    undirected.add_nodes_from(sorted(graph.nodes))
    for row in edges.sort_values(["src", "dst"]).itertuples(index=False):
        if row.src == row.dst:
            continue
        old = undirected.get_edge_data(int(row.src), int(row.dst), {}).get("weight", 0.0)
        undirected.add_edge(int(row.src), int(row.dst), weight=old + float(row.sum_kzt))
    nonisolated = [v for v, degree in undirected.degree if degree]
    communities = list(nx.community.louvain_communities(
        undirected.subgraph(nonisolated).copy(), weight="weight", seed=42)) if nonisolated else []
    communities += [{v} for v in nx.isolates(undirected)]
    communities.sort(key=lambda members: min(members))
    cluster_map = {gid: i for i, members in enumerate(communities) for gid in members}
    features["cluster_id"] = features.gid.map(cluster_map)
    rows = features.astype(object).where(pd.notna(features), None).to_dict(orient="records")
    for row in rows:
        row["gid"] = str(row["gid"])
    links = edges.to_dict(orient="records")
    for row in links:
        row["src"], row["dst"] = str(row["src"]), str(row["dst"])
    args.out.mkdir(parents=True, exist_ok=True)
    source, target = args.out / "input.json", args.out / "result.json"
    source.write_text(json.dumps(dict(schema_version="1.0", nodes=rows, edges=links),
                                 ensure_ascii=False, allow_nan=False), encoding="utf-8")
    engine_started = time.perf_counter()
    subprocess.run([str(args.engine.resolve()), str(source.resolve()), str(target.resolve())], check=True)
    engine_seconds = time.perf_counter() - engine_started
    result = json.loads(target.read_text(encoding="utf-8"))
    indexed = {row["gid"]: row for row in result["nodes"]}
    assert len(indexed) == len(nodes) == len(result["nodes"])
    assert set(indexed) == set(map(str, nodes.gid))
    assert len(result["top_nodes"]) == min(20, len(nodes))
    allowed_roles = set(starter.ROLES)
    for row in result["nodes"]:
        assert row["role"] in allowed_roles
        assert 0 <= row["role_score"] <= 1 and 0 <= row["priority_score"] <= 1
        assert row["evidence"] and len(row["evidence"]) <= 200
        assert row["why"] and len(row["why"]) <= 200
        assert row["cluster_id"] == cluster_map[int(row["gid"])]
        assert not (row["features"]["boundary_node"] and row["role"] in {"terminal", "transit"})
        if row["role"] in {"terminal", "transit"}:
            assert "SEED_INCOMING_INCOMPLETE" not in row["warnings"]

    # Independent NetworkX oracle: direction, cycles, isolates, and exclusion of self-seed.
    expected_reach = Counter()
    for gid in nodes.loc[nodes.is_seed, "gid"]:
        expected_reach.update(nx.descendants(graph, int(gid)))
    for gid, row in indexed.items():
        assert row["features"]["seed_reach_count"] == expected_reach[int(gid)]
    report = {
        "nodes": len(nodes), "edges": len(edges), "transactions": len(transactions),
        "seed_count": int(nodes.is_seed.sum()), "isolated_nodes": nx.number_of_isolates(graph),
        "clusters_in_test_adapter": len(communities),
        "boundary_nodes": sum(row["features"]["boundary_node"] for row in result["nodes"]),
        "roles": dict(sorted(Counter(row["role"] for row in result["nodes"]).items())),
        "engine_seconds": round(engine_seconds, 4),
        "preparation_engine_and_validation_seconds": round(time.perf_counter() - started, 4),
        "max_evidence_characters": max((len(row["evidence"]) for row in result["nodes"]), default=0),
        "seed_reach_matches_networkx": True,
        "top_5": result["top_nodes"][:5],
    }
    (args.out / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
