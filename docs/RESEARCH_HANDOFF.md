# Fusion1 research handoff

Fusion1 is the practical fusion of several earlier experiments, stripped of their speculative language.

## What is inherited

- **TheClutch2**: cheap persistent behavior should be the default; expensive planning is admitted only when needed.
- **DidItChange**: noisy observation change is not the same as meaningful state change.
- **WidePresent**: distinguish world/valid time, knowledge/arrival time, validity, incomplete evidence, and refresh cost.
- **PresentMoment**: distinguish state that exists from state that is currently accessible; explicitly represent work already in flight and the option to wait.
- **DifferentMachine**: research hypothesis that machine size need not equal active computation. It is *not* in the v0 critical path.
- **Vahti**: metrics controlling admission need adversarial tests; degenerate surprise metrics can silently destroy a scheduler.

## v0 claim

Fusion1 does not claim a new scheduling theory. It provides one runtime surface on which several existing disciplines can be compared while preserving state that ordinary stateless AI loops often discard.

The v0 control plane tracks:

```text
recorded source state
    -> dependency versions
    -> cached computations
    -> probabilistic age/validity
    -> cheap probes
    -> equivalent work in flight
    -> explicit compute budget
    -> REUSE / WAIT / PROBE / WAKE / HOLD
```

## First kill gates

1. **Exact dependencies:** Fusion should not beat exact dependency invalidation. It should tie it. If it spends more, fix the runtime.
2. **Uncertain external state:** a cheap confirming probe must save real expensive calls relative to a blind TTL refresh policy.
3. **In-flight work:** the runtime must avoid duplicate expensive work when an equivalent result is already pending.
4. **Real costs next:** synthetic cost units are only arithmetic checks. The next benchmark must use wall-clock measurements or paid/model-call counts from a real workflow.
5. **Conductor/phase quarantined:** rhythmic/global-phase coordination is not part of v0. It only enters after a multi-worker control-bandwidth benchmark exists.

## Next experiment

Use a real repository workflow with read-only commands:

```text
cheap recorded state: git diff/status, process/job metadata
expensive measured state: tests, docs build, render, model call
```

Randomly change one branch of the workflow and repeatedly request a downstream goal such as `publish_ready`.

Compare:

```text
always recompute
TTL refresh
dependency invalidation
Fusion1
oracle
```

Report correctness, wall time, duplicate work, probes, wakes, waits, and control-plane overhead.
