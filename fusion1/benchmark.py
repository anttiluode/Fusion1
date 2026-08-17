from __future__ import annotations

from dataclasses import dataclass

from .core import Conductor, NodeSpec


@dataclass(frozen=True)
class Row:
    scenario: str
    policy: str
    cost: float
    wakes: int
    probes: int
    waits: int


def exact_dependency_scenario() -> list[Row]:
    c = Conductor()
    c.register_source("code", "v0")
    c.register_node(NodeSpec("tests", lambda d: f"PASS:{d['code']}", ("code",), compute_cost=20))
    c.register_node(NodeSpec("package", lambda d: f"PKG:{d['tests']}", ("tests",), compute_cost=5))

    for t in range(100):
        if t in {20, 50, 80}:
            c.update_source("code", f"v{t}", now=float(t))
        c.resolve("package", now=float(t))

    m = c.metrics()["actions"]
    fusion = Row("versioned_dependency", "fusion", c.total_cost, m["WAKE"], m["PROBE"], m["WAIT"])
    dep_oracle = Row("versioned_dependency", "dependency_oracle", 100.0, 8, 0, 0)
    ttl = Row("versioned_dependency", "ttl_10", 250.0, 20, 0, 0)
    always = Row("versioned_dependency", "always", 2500.0, 200, 0, 0)
    return [fusion, dep_oracle, ttl, always]


def uncertain_external_scenario() -> list[Row]:
    hidden = {"epoch": 0}

    def compute(_: dict[str, object]) -> int:
        return hidden["epoch"]

    def probe(cached: int, _: float) -> bool:
        return cached == hidden["epoch"]

    c = Conductor()
    c.register_node(
        NodeSpec(
            "external_semantic_state",
            compute,
            compute_cost=25,
            probe=probe,
            probe_cost=1,
            hazard_per_second=0.12,
            reuse_threshold=0.82,
        )
    )

    for t in range(100):
        if t in {30, 70}:
            hidden["epoch"] += 1
        c.resolve("external_semantic_state", now=float(t))

    m = c.metrics()["actions"]
    fusion = Row("uncertain_external", "fusion", c.total_cost, m["WAKE"], m["PROBE"], m["WAIT"])
    ttl5 = Row("uncertain_external", "ttl_5", 500.0, 20, 0, 0)
    always = Row("uncertain_external", "always", 2500.0, 100, 0, 0)
    return [fusion, ttl5, always]


def in_flight_scenario() -> list[Row]:
    c = Conductor()
    c.register_node(NodeSpec("render", lambda _: "done", compute_cost=25))
    c.start_pending("render", "done", ready_at=5.0)
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        c.resolve("render", now=t)
    m = c.metrics()["actions"]
    fusion = Row("in_flight", "fusion", c.total_cost, m["WAKE"], m["PROBE"], m["WAIT"])
    duplicate = Row("in_flight", "duplicate_naive", 100.0, 4, 0, 0)
    return [fusion, duplicate]


def run() -> list[Row]:
    return exact_dependency_scenario() + uncertain_external_scenario() + in_flight_scenario()


def main() -> None:
    rows = run()
    print("Fusion1 v0 benchmark")
    print("scenario                policy               cost   wake probe wait")
    print("----------------------  -----------------  ------  ---- ----- ----")
    for r in rows:
        print(f"{r.scenario:22}  {r.policy:17}  {r.cost:6.1f}  {r.wakes:4d} {r.probes:5d} {r.waits:4d}")
    print()
    print("Interpretation:")
    print("- With exact versioned dependencies, Fusion should tie the dependency oracle.")
    print("- With uncertain external state, cheap probes can avoid expensive semantic refreshes.")
    print("- With equivalent work already in flight, WAIT prevents duplicate compute.")


if __name__ == "__main__":
    main()
