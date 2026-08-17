import unittest

from fusion1.benchmark import run


class BenchmarkTests(unittest.TestCase):
    def test_fusion_ties_dependency_oracle_and_beats_naive_policies(self):
        rows = run()
        by = {(r.scenario, r.policy): r for r in rows}
        self.assertEqual(
            by[("versioned_dependency", "fusion")].cost,
            by[("versioned_dependency", "dependency_oracle")].cost,
        )
        self.assertLess(
            by[("uncertain_external", "fusion")].cost,
            by[("uncertain_external", "ttl_5")].cost,
        )
        self.assertEqual(by[("in_flight", "fusion")].cost, 0)
        self.assertGreater(by[("in_flight", "fusion")].waits, 0)


if __name__ == "__main__":
    unittest.main()
