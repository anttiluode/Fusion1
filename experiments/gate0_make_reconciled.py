#!/usr/bin/env python3
"""Gate 0c — make baseline, with PROBE and WAIT no longer conflated.

This is a deliberately small simulator. It tests only the value of a perfect,
paid probe for an opaque source. WAIT is excluded because immediate-demand
semantics do not give it a fair job; it gets a separate real/asynchronous gate.

Fairness rules:
- observable sources are checked exactly and therefore contribute no residual hazard;
- the world uses Bernoulli change probability p/tick, so survival is (1-p)**age;
- refreshing an opaque dependency observes the input it computes from, so refresh
  does not pay a separate probe/check fee;
- PROBE is chosen only when its full expected loss beats both REUSE and REFRESH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import statistics
from typing import Dict, List


@dataclass
class Source:
    observable: bool
    check_cost: float
    change_probability: float
    version: int = 0


@dataclass
class Node:
    dep_sources: List[str] = field(default_factory=list)
    dep_nodes: List[str] = field(default_factory=list)
    refresh_cost: float = 1.0
    computed_tick: int = -1
    input_versions: Dict[str, int] = field(default_factory=dict)
    valid_cache: bool = False


class Ledger:
    def __init__(self) -> None:
        self.cost = 0.0
        self.actions: Dict[str, int] = {}

    def charge(self, action: str, amount: float) -> None:
        self.cost += amount
        self.actions[action] = self.actions.get(action, 0) + 1


def build(remote_hazard: float, src_hazard: float = 0.05):
    sources = {
        "src_files": Source(True, 0.05, src_hazard),
        "remote_ci": Source(False, 5.0, remote_hazard),
    }
    graph = {
        "tests": Node(["src_files"], [], 48.0),
        "docs": Node(["src_files"], [], 8.0),
        "package": Node(["remote_ci"], [], 12.0),
        "publish": Node([], ["tests", "docs", "package"], 2.0),
    }
    return sources, graph


def order(graph: Dict[str, Node], target: str) -> List[str]:
    out: List[str] = []
    seen = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for dep in graph[name].dep_nodes:
            visit(dep)
        out.append(name)

    visit(target)
    return out


def refresh(graph, sources, ledger: Ledger, name: str, tick: int) -> None:
    node = graph[name]
    ledger.charge(f"refresh:{name}", node.refresh_cost)
    node.input_versions = {s: sources[s].version for s in node.dep_sources}
    node.computed_tick = tick
    node.valid_cache = True


def correct(graph, sources, name: str) -> bool:
    node = graph[name]
    if not node.valid_cache:
        return False
    for s in node.dep_sources:
        if node.input_versions.get(s) != sources[s].version:
            return False
    return all(correct(graph, sources, dep) for dep in node.dep_nodes)


def p_invalid(node: Node, sources, tick: int) -> float:
    if not node.valid_cache:
        return 1.0
    age = max(0, tick - node.computed_tick)
    p_ok = 1.0
    for s in node.dep_sources:
        src = sources[s]
        if src.observable:
            continue
        p_ok *= (1.0 - src.change_probability) ** age
    return 1.0 - p_ok


def serve(policy: str, graph, sources, ledger: Ledger, target: str, tick: int, c_wrong: float) -> None:
    dirty = set()

    for name in order(graph, target):
        node = graph[name]
        need = (not node.valid_cache) or any(dep in dirty for dep in node.dep_nodes)

        if policy == "always":
            for s in node.dep_sources:
                ledger.charge(f"check:{s}", sources[s].check_cost)
            refresh(graph, sources, ledger, name, tick)
            dirty.add(name)
            continue

        if policy == "oracle":
            if not need:
                need = any(node.input_versions.get(s) != sources[s].version for s in node.dep_sources)
            if need:
                refresh(graph, sources, ledger, name, tick)
                dirty.add(name)
            continue

        if policy == "make":
            for s in node.dep_sources:
                src = sources[s]
                if src.observable:
                    ledger.charge(f"check:{s}", src.check_cost)
                    if node.input_versions.get(s) != src.version:
                        need = True
                else:
                    need = True
            if need:
                refresh(graph, sources, ledger, name, tick)
                dirty.add(name)
            continue

        opaque = []
        for s in node.dep_sources:
            src = sources[s]
            if src.observable:
                ledger.charge(f"check:{s}", src.check_cost)
                if node.input_versions.get(s) != src.version:
                    need = True
            else:
                opaque.append(s)

        if need:
            refresh(graph, sources, ledger, name, tick)
            dirty.add(name)
            continue

        p_bad = p_invalid(node, sources, tick)
        reuse_loss = p_bad * c_wrong
        refresh_loss = node.refresh_cost

        if policy == "risk":
            if refresh_loss < reuse_loss:
                refresh(graph, sources, ledger, name, tick)
                dirty.add(name)
            continue

        if policy != "probe":
            raise ValueError(policy)

        probe_cost = sum(sources[s].check_cost for s in opaque)
        probe_loss = probe_cost + p_bad * refresh_loss if opaque else float("inf")

        action, _ = min(
            [("reuse", reuse_loss), ("refresh", refresh_loss), ("probe", probe_loss)],
            key=lambda item: item[1],
        )

        if action == "refresh":
            refresh(graph, sources, ledger, name, tick)
            dirty.add(name)
        elif action == "probe":
            changed = False
            for s in opaque:
                ledger.charge(f"probe:{s}", sources[s].check_cost)
                if node.input_versions.get(s) != sources[s].version:
                    changed = True
            if changed:
                refresh(graph, sources, ledger, name, tick)
                dirty.add(name)
            else:
                node.computed_tick = tick


def run(
    policy: str,
    seed: int,
    ticks: int,
    remote_hazard: float,
    c_wrong: float,
    *,
    src_hazard: float = 0.05,
    demand_probability: float = 0.25,
):
    rng = random.Random(seed)
    sources, graph = build(remote_hazard, src_hazard)
    ledger = Ledger()
    served = wrong = 0

    for tick in range(1, ticks + 1):
        for src in sources.values():
            if rng.random() < src.change_probability:
                src.version += 1

        if rng.random() >= demand_probability:
            continue

        serve(policy, graph, sources, ledger, "publish", tick, c_wrong)
        served += 1
        if not correct(graph, sources, "publish"):
            wrong += 1

    return {
        "paid": ledger.cost,
        "wrong": wrong,
        "served": served,
        "score": ledger.cost + c_wrong * wrong,
        "actions": dict(ledger.actions),
    }


def mean_score(policy: str, hazard: float, c_wrong: float, seeds: int = 12, ticks: int = 400) -> float:
    return statistics.mean(
        run(policy, 1000 + seed, ticks, hazard, c_wrong)["score"]
        for seed in range(seeds)
    )


def phase_grid():
    hazards = [0.002, 0.01, 0.05, 0.2, 0.6]
    wrong_costs = [2.0, 8.0, 25.0, 60.0, 200.0]
    out = {}
    for c_wrong in wrong_costs:
        for hazard in hazards:
            make = mean_score("make", hazard, c_wrong)
            risk = mean_score("risk", hazard, c_wrong)
            probe = mean_score("probe", hazard, c_wrong)
            out[(c_wrong, hazard)] = {
                "make": make,
                "risk": risk,
                "probe": probe,
                "risk_vs_make_pct": (make - risk) / make * 100.0,
                "probe_vs_make_pct": (make - probe) / make * 100.0,
            }
    return out


def main() -> None:
    hazards = [0.002, 0.01, 0.05, 0.2, 0.6]
    wrong_costs = [2.0, 8.0, 25.0, 60.0, 200.0]
    grid = phase_grid()

    print("Gate 0c — fair make / risk / probe ablation")
    print("positive percentage = policy beats make")
    for label, key in [("risk", "risk_vs_make_pct"), ("probe", "probe_vs_make_pct")]:
        print(f"\n{label} vs make")
        header = "C_wrong \\ hazard"
        print(f"{header:>16} | " + " | ".join(f"{h:>8}" for h in hazards))
        print("-" * 72)
        for c_wrong in wrong_costs:
            vals = [grid[(c_wrong, h)][key] for h in hazards]
            print(f"{c_wrong:16.0f} | " + " | ".join(f"{v:+8.1f}" for v in vals))

    print("\nPROBE decision rule:")
    print("  reuse   = P(invalid) * C_wrong")
    print("  refresh = C_refresh")
    print("  probe   = C_probe + P(invalid) * C_refresh")
    print("Choose the minimum. WAIT is deliberately not tested here.")


if __name__ == "__main__":
    main()
