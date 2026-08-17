# Fusion1

**A control plane for persistent AI computation.**

Fusion1 tracks what is still valid, what is demanded, what is already happening, and what is worth recomputing so expensive work runs only where it can change the outcome.

This repository is deliberately small. It is not claiming a new scheduling theory. The first goal is to turn several earlier research threads into one testable runtime with boring baselines and explicit kill gates.

## The v0 control loop

```text
recorded / observed state
          |
          v
   dependency versions
          |
          v
 cached computation ---- equivalent work already in flight
          |                         |
          v                         v
  validity / uncertainty          WAIT
          |
          +---- cheap probe? ----> PROBE
          |
          +---- still valid -----> REUSE
          |
          +---- budget denied ---> HOLD
          |
          `---- worth refresh ---> WAKE
```

The runtime currently supports five admission decisions:

- `REUSE` — keep a cached result.
- `WAIT` — equivalent work is already in flight.
- `PROBE` — spend a small amount to test whether an expensive cached result remains usable.
- `WAKE` — execute the expensive computation.
- `HOLD` — do not admit work because the explicit budget cannot pay for it.

## Why this is a fusion

The implementation borrows practical pieces from earlier Antti Luode repositories while quarantining their speculative claims:

- **TheClutch2** — cheap persistent behavior first, expensive work on demand.
- **DidItChange** — noisy change is not necessarily meaningful change.
- **WidePresent** — validity is richer than scalar age; preserve temporal/provenance state and refresh by utility.
- **PresentMoment** — state may exist without being currently usable; unfinished/in-flight work is part of the present runtime state.
- **DifferentMachine** — the research hypothesis that machine size need not equal active computation. It is *not* in the v0 critical path.
- **Vahti** — admission metrics need adversarial tests before they are trusted.

See [`docs/RESEARCH_HANDOFF.md`](docs/RESEARCH_HANDOFF.md).

## Quick start

No runtime dependencies are required beyond Python 3.10+.

```bash
python -m unittest discover -s tests -v
python -m fusion1.benchmark
python experiments/gate0_make_reconciled.py
python examples/workflow_demo.py
```

## First benchmark

The benchmark is intentionally synthetic and uses visible cost units. It is an arithmetic/logic gate, not a product-performance claim.

Current local run:

```text
Fusion1 v0 benchmark
scenario                policy               cost   wake probe wait
----------------------  -----------------  ------  ---- ----- ----
versioned_dependency    fusion              100.0     8     0    0
versioned_dependency    dependency_oracle   100.0     8     0    0
versioned_dependency    ttl_10              250.0    20     0    0
versioned_dependency    always             2500.0   200     0    0
uncertain_external      fusion              124.0     3    47    0
uncertain_external      ttl_5               500.0    20     0    0
uncertain_external      always             2500.0   100     0    0
in_flight               fusion                0.0     0     0    4
in_flight               duplicate_naive     100.0     4     0    0
```

The controls matter more than the headline savings:

1. **Exact dependency information:** Fusion ties the exact dependency oracle. It should not beat it.
2. **Uncertain external state:** a cheap probe can confirm a cached semantic result without paying for the full refresh.
3. **In-flight state:** `WAIT` prevents duplicate work when the result is already coming.

The next benchmark must replace synthetic cost units with actual wall-clock time, model/tool calls, or money on a real workflow.

## Stronger Gate 0: `make` is the baseline

The first benchmark above is a runtime sanity check, not the strongest attacker.

Claude independently built a better Gate 0 around the baseline Fusion1 actually has to face: ordinary dependency invalidation. If exact dependency versions are available cheaply, Fusion should not pretend to beat `make`.

That attack also exposed a useful correction. The first bundled comparison tested:

```text
risk
vs
risk + PROBE + WAIT
```

so it could not tell which extra mechanism helped or hurt. An explicit ablation showed PROBE helping while WAIT dominated the loss in the immediate-demand world.

`experiments/gate0_make_reconciled.py` therefore tests only:

```text
make
risk
probe
```

with matched refresh costs, exact treatment of observable sources, the correct discrete hazard law, and a full expected-cost rule for probing.

Representative local Gate 0c result, positive = beats `make`:

```text
PROBE vs make

C_wrong \ hazard |    .002 |     .01 |     .05 |      .2 |      .6
-----------------+---------+---------+---------+---------+---------
               2 |   +55.2 |   +51.3 |   +49.2 |   +48.9 |   +48.8
               8 |   +49.2 |   +33.7 |   +25.5 |   +24.0 |   +23.8
              25 |   +45.9 |   +37.2 |   +26.1 |   +10.6 |    +0.0
              60 |   +48.0 |   +43.1 |   +28.4 |   +10.4 |    +0.0
             200 |   +50.0 |   +40.5 |   +26.5 |   +10.4 |    +0.0
```

This is still a synthetic perfect-probe result. It says only that PROBE has a coherent value-of-information regime. **WAIT is quarantined rather than killed** until a benchmark gives every policy the same real asynchronous latency and some deadline slack.

See [`docs/GATE0_MAKE_RECONCILIATION.md`](docs/GATE0_MAKE_RECONCILIATION.md).

## Minimal API

```python
from fusion1 import Conductor, NodeSpec

runtime = Conductor()
runtime.register_source("code", "commit-A")

runtime.register_node(NodeSpec(
    "tests",
    lambda deps: run_tests(deps["code"]),
    dependencies=("code",),
    compute_cost=20,
))

result = runtime.resolve("tests", now=0.0)
print(result.action, result.value)
```

For uncertain external state, attach a cheaper probe and an age hazard:

```python
runtime.register_node(NodeSpec(
    "remote_state",
    expensive_refresh,
    compute_cost=25,
    probe=cheap_still_valid_check,
    probe_cost=1,
    hazard_per_second=0.12,
    reuse_threshold=0.82,
))
```

## Research boundary

`Fusion1` v0 does **not** contain an oscillatory/alpha/phase conductor. A global-phase scheduler only enters after there is a multi-worker benchmark where control bandwidth itself is a measured resource.

The practical question comes first:

> Can maintaining validity, dependency, pending-work and measurement-cost state avoid real expensive work without losing correctness?

If not, keep the boring dependency graph and stop.
