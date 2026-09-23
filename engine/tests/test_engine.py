"""CLI regression tests; Python standard library only. No dataset dependencies."""
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(sys.argv.pop(1)).resolve()


def graph(definitions, edges):
    nodes = {}
    for gid, attrs in definitions.items():
        row = dict(gid=str(gid), depth=1, is_seed=False, cluster_id=0,
                   in_deg=0, out_deg=0, in_kzt=0.0, out_kzt=0.0,
                   in_tx=0, out_tx=0, pagerank=0.0)
        row.update(attrs)
        nodes[str(gid)] = row
    links = []
    for src, dst, amount, count in edges:
        src, dst = str(src), str(dst)
        links.append(dict(src=src, dst=dst, sum_kzt=amount, n_tx=count))
        nodes[src]["out_deg"] += 1
        nodes[dst]["in_deg"] += 1
        nodes[src]["out_kzt"] += amount
        nodes[dst]["in_kzt"] += amount
        nodes[src]["out_tx"] += count
        nodes[dst]["in_tx"] += count
    for row in nodes.values():
        row["pass_through"] = row["out_kzt"] / row["in_kzt"] if row["in_kzt"] else None
        row["truncated_by_depth"] = row["depth"] == 4 and row["out_deg"] == 0
    return dict(schema_version="1.0", nodes=list(nodes.values()), edges=links)


def motifs():
    definitions = {i: dict(is_seed=True, depth=0) for i in range(1, 10)}
    definitions.update({i: {} for i in [10, 11, 12, 20, 21, 30, 31, 32, 33, 34, 35, 36, 40, 41, 50, 60, 99]})
    definitions[11] = dict(cluster_id=1)
    definitions[12] = dict(cluster_id=2)
    definitions[50] = dict(depth=4)
    edges = [(s, 10, 100_000, 2) for s in [1, 2, 3]]
    edges += [(10, 11, 150_000, 3), (10, 12, 150_000, 3)]
    edges += [(s, 20, 50_000, 1) for s in [4, 5, 6]]
    edges += [(20, 21, 10_000, 1), (7, 30, 120_000, 6)]
    edges += [(30, d, 20_000, 1) for d in range(31, 37)]
    edges += [(8, 40, 25_000, 1), (40, 41, 25_000, 1), (9, 50, 100_000, 1), (60, 60, 1e12, 4)]
    return graph(definitions, edges)


def nested_input(flat):
    nested = copy.deepcopy(flat)
    fields = ["in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "pagerank", "pass_through"]
    for row in nested["nodes"]:
        row["metrics"] = {field: row.pop(field) for field in fields if field in row}
        row["flags"] = {"truncated_by_depth": row.pop("truncated_by_depth", False)}
    return nested


class EngineTests(unittest.TestCase):
    def invoke(self, data, config=None, raw=False, success=True, unicode_paths=False, named=False):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / ("Проверка ядра" if unicode_paths else "case")
            folder.mkdir()
            source, target = folder / "input.json", folder / "result.json"
            source.write_text(data if raw else json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            target.write_text("previous successful result", encoding="utf-8")
            args = [str(ENGINE), "--input", str(source), "--output", str(target)] if named else [str(ENGINE), str(source), str(target)]
            if config is not None:
                config_path = folder / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                args += ["--config", str(config_path)]
            process = subprocess.run(args, capture_output=True, encoding="utf-8", timeout=20)
            output = target.read_text(encoding="utf-8")
            if success:
                self.assertEqual(process.returncode, 0, process.stderr)
                return json.loads(output)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(output, "previous successful result")
            self.assertIn("engine:", process.stderr)
            return process.stderr

    def test_all_six_roles(self):
        result = self.invoke(motifs())
        rows = {r["gid"]: r for r in result["nodes"]}
        expected = {"10": "coordinator", "20": "consolidator", "30": "distributor",
                    "40": "transit", "41": "terminal", "99": "peripheral"}
        for gid, role in expected.items():
            self.assertEqual(rows[gid]["role"], role)
        self.assertEqual(len(result["top_nodes"]), 20)
        for row in result["nodes"]:
            for key in ["role_score", "priority_score"]:
                self.assertTrue(0 <= row[key] <= 1)
            for key in ["evidence", "why"]:
                self.assertTrue(0 < len(row[key]) <= 200)
                self.assertTrue(any(c.isdigit() for c in row[key]))
            contributions = sum(x["contribution"] for x in row["priority_breakdown"].values())
            self.assertAlmostEqual(row["priority_score"], contributions)

    def test_boundary_not_terminal(self):
        row = next(r for r in self.invoke(motifs())["nodes"] if r["gid"] == "50")
        self.assertEqual(row["role"], "peripheral")
        self.assertTrue(row["features"]["truncated_by_depth"])
        self.assertIn("OUTGOING_INCOMPLETE_AT_DEPTH_LIMIT", row["warnings"])

    def test_boundary_can_still_consolidate(self):
        data = graph({**{s: dict(is_seed=True, depth=0) for s in [1, 2, 3]}, 4: dict(depth=4)},
                     [(s, 4, 10000, 1) for s in [1, 2, 3]])
        row = self.invoke(data)["nodes"][-1]
        self.assertEqual(row["role"], "consolidator")
        self.assertLessEqual(row["role_score"], 0.8)

    def test_seed_ratio_does_not_make_transit(self):
        data = graph({1: {}, 2: dict(is_seed=True, depth=0), 3: {}}, [(1, 2, 10000, 1), (2, 3, 10000, 1)])
        row = self.invoke(data)["nodes"][1]
        self.assertEqual(row["role"], "peripheral")
        self.assertIn("SEED_INCOMING_INCOMPLETE", row["warnings"])

    def test_cycles_reachability_and_direction(self):
        data = graph({1: dict(is_seed=True, depth=0), 2: {}, 3: dict(is_seed=True, depth=0), 4: {}, 5: {}},
                     [(1, 2, 5000, 1), (2, 3, 5000, 1), (3, 1, 5000, 1), (4, 2, 5000, 1)])
        rows = self.invoke(data)["nodes"]
        self.assertEqual([r["features"]["seed_reach_count"] for r in rows], [1, 2, 1, 0, 0])
        self.assertEqual(rows[0]["features"]["min_seed_hops"], 1)
        self.assertIsNone(rows[-1]["features"]["min_seed_hops"])

    def test_cross_cluster_and_unique_counterparties(self):
        data = graph({1: {}, 2: dict(cluster_id=2), 3: dict(cluster_id=2), 4: dict(cluster_id=3)},
                     [(1, 2, 5000, 1), (2, 1, 5000, 1), (1, 3, 5000, 1), (4, 1, 5000, 1)])
        f = self.invoke(data)["nodes"][0]["features"]
        self.assertEqual((f["external_cluster_count"], f["cross_cluster_edges"], f["counterparty_count"]), (2, 4, 3))

    def test_self_transfer_is_not_transit_or_high_priority(self):
        row = next(r for r in self.invoke(motifs())["nodes"] if r["gid"] == "60")
        self.assertEqual(row["role"], "peripheral")
        self.assertEqual(row["priority_score"], 0)

    def test_isolates_and_numeric_ties(self):
        data = graph({10: {}, 2: {}, 100: dict(is_seed=True, depth=0)}, [])
        result = self.invoke(data)
        self.assertEqual([r["gid"] for r in result["top_nodes"]], ["2", "10", "100"])
        self.assertTrue(all(r["priority_score"] == 0 for r in result["nodes"]))

    def test_empty_graph(self):
        result = self.invoke(graph({}, []))
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["top_nodes"], [])

    def test_input_order_does_not_change_result(self):
        data = motifs()
        first = self.invoke(data)
        random.Random(27).shuffle(data["nodes"])
        random.Random(91).shuffle(data["edges"])
        self.assertEqual(first, self.invoke(data))

    def test_int64_identifiers_and_unicode_paths(self):
        ids = [-9223372036854775808, 9223372036854775807]
        result = self.invoke(graph({i: {} for i in ids}, []), unicode_paths=True)
        self.assertEqual([r["gid"] for r in result["nodes"]], list(map(str, ids)))

    def test_invalid_ids(self):
        for gid in [123, 1.5, "01", "-0", "+1", "abc", "9223372036854775808", ""]:
            with self.subTest(gid=gid):
                data = graph({1: {}}, [])
                data["nodes"][0]["gid"] = gid
                self.invoke(data, success=False)

    def test_duplicate_and_missing_endpoints(self):
        for kind in ["node", "edge", "endpoint"]:
            data = motifs()
            if kind == "node": data["nodes"].append(data["nodes"][0])
            if kind == "edge": data["edges"].append(data["edges"][0])
            if kind == "endpoint": data["edges"][0]["dst"] = "999999"
            with self.subTest(kind=kind): self.invoke(data, success=False)

    def test_inconsistent_features_are_rejected(self):
        for field, value in [("in_deg", 100), ("out_kzt", 3), ("in_tx", 2),
                             ("pass_through", 99), ("truncated_by_depth", True),
                             ("cluster_id", -1), ("depth", 5), ("is_seed", "false"),
                             ("pagerank", 2), ("out_tx", 1.5)]:
            data = motifs()
            data["nodes"][0][field] = value
            with self.subTest(field=field): self.invoke(data, success=False)

    def test_invalid_json(self):
        for raw in ['{"nodes": NaN}', '{"schema_version":"1.0"} garbage', '{', 'null']:
            with self.subTest(raw=raw): self.invoke(raw, raw=True, success=False)

    def test_missing_fields_and_version(self):
        data = motifs()
        del data["nodes"][0]["cluster_id"]
        self.invoke(data, success=False)
        data = motifs()
        data["schema_version"] = "2.0"
        self.invoke(data, success=False)

    def test_invalid_config(self):
        for config in [{"typo": 1}, {"priority_weights": {"volume": 0.9}},
                       {"transit_ratio_min": 1.1}, {"consolidator_min_senders": 2.5},
                       {"boundary_role_multiplier": 1.1}, {"priority_seed_saturation": 0}]:
            with self.subTest(config=config): self.invoke(motifs(), config=config, success=False)

    def test_config_override_changes_rules(self):
        result = self.invoke(motifs(), config={"distributor_min_receivers": 100})
        row = next(r for r in result["nodes"] if r["gid"] == "30")
        self.assertNotEqual(row["role"], "distributor")

    def test_boundary_observed_outgoing_still_cannot_be_transit(self):
        data = graph({1: {}, 2: dict(depth=4), 3: {}}, [(1, 2, 10000, 1), (2, 3, 10000, 1)])
        self.assertEqual(self.invoke(data)["nodes"][1]["role"], "peripheral")

    def test_random_reachability_matches_reference(self):
        rng = random.Random(42)
        definitions = {i: dict(is_seed=i < 5, depth=0 if i < 5 else 1) for i in range(40)}
        edges = [(a, b, rng.randint(1, 30) * 5000, 1) for a in definitions for b in definitions if rng.random() < 0.06]
        result = self.invoke(graph(definitions, edges))
        expected = {i: set() for i in definitions}
        for seed in range(5):
            reached = {seed}
            while True:
                expanded = reached | {b for a, b, _, _ in edges if a in reached}
                if expanded == reached: break
                reached = expanded
            for target in reached - {seed}: expected[target].add(seed)
        for row in result["nodes"]:
            self.assertEqual(row["features"]["seed_reach_count"], len(expected[int(row["gid"])]))

    def test_checked_in_example_and_default_config(self):
        root = Path(__file__).resolve().parents[1]
        expected_config = json.loads((root / "config/default.json").read_text(encoding="utf-8"))
        process = subprocess.run([str(ENGINE), "--print-config"], capture_output=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(process.stdout), expected_config)
        self.invoke(json.loads((root / "examples/input.json").read_text(encoding="utf-8")))

    def test_nested_and_flat_with_both_cli_styles_are_identical(self):
        flat = motifs()
        expected = self.invoke(flat)
        for payload in [flat, nested_input(flat)]:
            for named in [False, True]:
                with self.subTest(nested="metrics" in payload["nodes"][0], named=named):
                    self.assertEqual(self.invoke(payload, named=named, unicode_paths=True), expected)
        self.assertEqual(expected["engine"], "money-graph-cpp/" + expected["engine_version"])

    def test_nested_config_overrides_preserve_canonical_scores(self):
        flat = motifs()
        config = {"distributor_min_receivers": 100}
        self.assertEqual(self.invoke(flat, config=config), self.invoke(nested_input(flat), config=config, named=True))

    def test_conflicting_flat_and_nested_fields_rejected(self):
        for group, field, value in [("metrics", "out_deg", 777), ("flags", "truncated_by_depth", True)]:
            data = motifs()
            data["nodes"][0][group] = {field: value}
            with self.subTest(field=field):
                self.assertIn("Conflicting", self.invoke(data, success=False, named=True))

    def test_identical_duplicate_fields_and_untrusted_extra_flags(self):
        flat = motifs()
        mixed = copy.deepcopy(flat)
        for row, nested in zip(mixed["nodes"], nested_input(flat)["nodes"]):
            row["metrics"] = nested["metrics"]
            row["metrics"]["gid"] = "123456789"  # must never override identity
            row["flags"] = {**nested["flags"], "pass_through_reliable": True}
        self.assertEqual(self.invoke(flat), self.invoke(mixed))

    def test_invalid_nested_shape_and_missing_metric(self):
        for field in ["metrics", "flags"]:
            data = nested_input(motifs())
            data["nodes"][0][field] = []
            self.invoke(data, success=False)
        data = nested_input(motifs())
        del data["nodes"][0]["metrics"]["pagerank"]
        self.invoke(data, success=False)

    def test_named_cli_argument_errors(self):
        for args in [["--input"], ["--input", "x"], ["--input", "x", "--output"],
                     ["--input", "x", "--output", "y", "--input", "z"],
                     ["x", "y", "--input", "x"], ["--unknown", "x"]]:
            with self.subTest(args=args):
                process = subprocess.run([str(ENGINE), *args], capture_output=True, encoding="utf-8", timeout=10)
                self.assertEqual(process.returncode, 2, process.stderr)

    def test_armans_checked_in_payload(self):
        root = Path(__file__).resolve().parents[2]
        nested = json.loads((root / "examples/input.json").read_text(encoding="utf-8"))
        flat = copy.deepcopy(nested)
        for row in flat["nodes"]:
            if "metrics" in row:
                row.update(row.pop("metrics"))
            row.update(row.pop("flags", {}))
        self.assertEqual(self.invoke(nested, named=True), self.invoke(flat))


if __name__ == "__main__":
    unittest.main()
