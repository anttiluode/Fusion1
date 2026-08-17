import json
import tempfile
import unittest

from fusion1 import Action, Budget, Conductor, NodeSpec


class FusionCoreTests(unittest.TestCase):
    def test_reuses_when_dependencies_unchanged(self):
        c = Conductor()
        c.register_source("x", 2)
        calls = {"n": 0}

        def compute(d):
            calls["n"] += 1
            return d["x"] * 3

        c.register_node(NodeSpec("y", compute, ("x",), compute_cost=4))
        first = c.resolve("y", now=0)
        second = c.resolve("y", now=1)
        self.assertEqual(first.action, Action.WAKE)
        self.assertEqual(second.action, Action.REUSE)
        self.assertEqual(second.value, 6)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(c.total_cost, 4)

    def test_source_change_invalidates_downstream(self):
        c = Conductor()
        c.register_source("code", "a")
        c.register_node(NodeSpec("tests", lambda d: d["code"].upper(), ("code",), compute_cost=10))
        a = c.resolve("tests", now=0)
        c.update_source("code", "b", now=1)
        b = c.resolve("tests", now=1)
        self.assertEqual(a.value, "A")
        self.assertEqual(b.value, "B")
        self.assertEqual(b.action, Action.WAKE)
        self.assertEqual(b.reason, "dependency_changed")
        self.assertEqual(c.total_cost, 20)

    def test_probe_confirms_uncertain_cache_without_wake(self):
        hidden = {"epoch": 7}
        calls = {"compute": 0, "probe": 0}

        def compute(_):
            calls["compute"] += 1
            return hidden["epoch"]

        def probe(cached, _now):
            calls["probe"] += 1
            return cached == hidden["epoch"]

        c = Conductor()
        c.register_node(NodeSpec(
            "remote",
            compute,
            compute_cost=20,
            probe=probe,
            probe_cost=1,
            hazard_per_second=1.0,
            reuse_threshold=0.9,
        ))
        self.assertEqual(c.resolve("remote", now=0).action, Action.WAKE)
        d = c.resolve("remote", now=1)
        self.assertEqual(d.action, Action.PROBE)
        self.assertEqual(calls, {"compute": 1, "probe": 1})
        self.assertEqual(c.total_cost, 21)

    def test_failed_probe_wakes_compute(self):
        hidden = {"epoch": 1}

        def compute(_):
            return hidden["epoch"]

        def probe(cached, _now):
            return cached == hidden["epoch"]

        c = Conductor()
        c.register_node(NodeSpec(
            "remote", compute, compute_cost=20, probe=probe, probe_cost=1,
            hazard_per_second=1.0, reuse_threshold=0.9,
        ))
        c.resolve("remote", now=0)
        hidden["epoch"] = 2
        d = c.resolve("remote", now=1)
        self.assertEqual(d.action, Action.WAKE)
        self.assertEqual(d.value, 2)
        self.assertEqual(c.total_cost, 41)

    def test_wait_when_equivalent_work_is_in_flight(self):
        c = Conductor()
        c.register_node(NodeSpec("render", lambda _: "new", compute_cost=50))
        c.start_pending("render", "finished", ready_at=5)
        self.assertEqual(c.resolve("render", now=2).action, Action.WAIT)
        done = c.resolve("render", now=5)
        self.assertEqual(done.action, Action.REUSE)
        self.assertEqual(done.value, "finished")
        self.assertEqual(c.total_cost, 0)

    def test_budget_can_hold_compute(self):
        c = Conductor(budget=Budget(capacity=3, balance=3))
        c.register_node(NodeSpec("big", lambda _: 99, compute_cost=5))
        d = c.resolve("big", now=0)
        self.assertEqual(d.action, Action.HOLD)
        self.assertIsNone(d.value)
        self.assertEqual(c.total_cost, 0)

    def test_jsonl_audit_log(self):
        c = Conductor()
        c.register_node(NodeSpec("x", lambda _: 1, compute_cost=1))
        c.resolve("x", now=0)
        c.resolve("x", now=1)
        with tempfile.TemporaryDirectory() as td:
            path = f"{td}/events.jsonl"
            c.write_jsonl(path)
            with open(path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
        self.assertEqual([r["action"] for r in rows], ["WAKE", "REUSE"])


if __name__ == "__main__":
    unittest.main()
