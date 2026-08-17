import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import gate0_make_reconciled as gate


class Gate0ReconciledTests(unittest.TestCase):
    def test_make_is_flat_in_remote_hazard(self):
        low = gate.mean_score("make", 0.002, 60.0, seeds=4, ticks=150)
        high = gate.mean_score("make", 0.6, 60.0, seeds=4, ticks=150)
        self.assertAlmostEqual(low, high, places=9)

    def test_probe_beats_risk_in_information_value_regime(self):
        risk = gate.mean_score("risk", 0.05, 60.0, seeds=8, ticks=300)
        probe = gate.mean_score("probe", 0.05, 60.0, seeds=8, ticks=300)
        self.assertLess(probe, risk)

    def test_high_hazard_converges_to_conservative_refresh(self):
        make = gate.mean_score("make", 0.6, 200.0, seeds=6, ticks=250)
        risk = gate.mean_score("risk", 0.6, 200.0, seeds=6, ticks=250)
        probe = gate.mean_score("probe", 0.6, 200.0, seeds=6, ticks=250)
        self.assertAlmostEqual(risk, make, places=9)
        self.assertAlmostEqual(probe, make, places=9)

    def test_observable_source_is_exact_not_probabilistic(self):
        sources, graph = gate.build(remote_hazard=0.0, src_hazard=0.9)
        ledger = gate.Ledger()
        gate.serve("risk", graph, sources, ledger, "publish", 1, c_wrong=200.0)
        paid = ledger.cost
        for tick in range(2, 10):
            gate.serve("risk", graph, sources, ledger, "publish", tick, c_wrong=200.0)
        self.assertLess(ledger.cost - paid, 1.0)


if __name__ == "__main__":
    unittest.main()
