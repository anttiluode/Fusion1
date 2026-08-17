# Gate 0 reconciliation — `make`, PROBE, and WAIT

Date: 2026-08-17

Claude's independent Gate 0 was a stronger attacker than Fusion1's first synthetic benchmark because it put the correct boring baseline in the room:

> if exact dependency versions are cheap and available, ordinary build-system invalidation should win or tie.

The supplied benchmark also introduced the right difficult case: an opaque remote source whose current version cannot be hashed for free.

I reproduced the supplied runs exactly. The headline `conductor = risk + PROBE + WAIT` result is real for that code. The interpretation needed one more ablation.

## 1. The bundled negative did not identify which mechanism failed

The supplied policies define:

```text
risk        = validity posterior only
conductor   = risk + PROBE + WAIT
```

There was no `probe_only` or `wait_only` row.

Adding those two subclasses without otherwise changing the supplied simulator gives, for one representative cell:

```text
C_wrong = 60, remote hazard = 0.05

risk         2936.5
PROBE only   2684.7
WAIT only    4409.6
conductor    4157.3
make         2376.0
```

So PROBE improved the validity-only policy in that cell. WAIT dominated the bundled loss.

At:

```text
C_wrong = 25, remote hazard = 0.05

risk         2185.5
PROBE only   1963.9
WAIT only    2750.5
conductor    2573.9
make         2376.0
```

PROBE-only beats `make`, while the bundled conductor loses to it.

Therefore the statement "PROBE and WAIT did not earn their place" is not supported by the bundled comparison. The supported statement is narrower:

> WAIT does not earn its place in an immediate-demand benchmark, and can erase a PROBE gain when it is bundled into the same policy.

## 2. Four fairness corrections

The supplied simulator also mixed several semantics that make the phase diagram hard to interpret causally.

### Exact observable state must remove uncertainty

`Risk.serve()` checks observable sources exactly, but `_p_invalid()` then re-adds hazard for those same sources. Once the current version has just been verified equal to the cached input version, its residual invalidity probability at that decision point is zero.

Gate 0c excludes observable sources from the posterior after their exact check.

### Bernoulli world and exponential posterior were mismatched

The world changes a source independently with probability `p` each tick.

The exact probability of no change for `age` ticks is:

```text
(1 - p) ** age
```

not:

```text
exp(-p * age)
```

The exponential is a useful approximation only when `p` is small, but the original sweep goes as high as `p = 0.6`.

Gate 0c uses the exact discrete survival law.

### Refresh should not also pay for a separate probe

The supplied core says an opaque source can be learned either by paying the probe/check cost **or by running the expensive job itself**.

`make` follows that rule: it refreshes an opaque dependency and pays only refresh cost.

`risk` / `conductor` instead paid `world.read()` for the opaque source and then paid refresh cost as well. That gives the probabilistic policies an extra fee that the conservative baseline does not pay for the same refresh.

Gate 0c treats refresh as observing the source state it computes from; a separate probe is charged only when the policy chooses PROBE.

### PROBE must beat both alternatives on full expected cost

For a perfect probe:

```text
reuse   = P(invalid) * C_wrong
refresh = C_refresh
probe   = C_probe + P(invalid) * C_refresh
```

PROBE is chosen only when its full expected cost is lower than both REUSE and REFRESH.

This is stricter than separately checking `P(invalid)*C_wrong > C_probe` and `C_probe < (1-P(invalid))*C_refresh`.

## 3. WAIT is quarantined, not killed

The supplied benchmark gives every demand an answer immediately.

At the same time, `Risk` and `make` can make a node with `refresh_ticks > 0` become fresh synchronously, while `Conductor` alone sometimes launches it asynchronously and waits. That changes execution semantics as well as policy.

So Gate 0c deliberately removes WAIT.

WAIT needs a separate world with:

```text
real asynchronous latency
deadline slack / deferral
same completion semantics for every policy
duplicate-work accounting
stale-service or missed-deadline cost
```

Until then the result is:

> WAIT has no demonstrated value in Fusion1, but the current immediate-demand benchmark is not a fair kill gate for it.

## 4. Reconciled Gate 0c

`experiments/gate0_make_reconciled.py` compares only:

```text
make
risk
probe
```

under the corrected rules above.

Local result, positive = beats `make`:

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

This is **not** a product result. The probe is perfect, hazards are known, and costs are still synthetic/structured. The useful result is only that the expected-value logic is now internally fair and that PROBE has a coherent middle regime instead of being bundled with WAIT.

At very high hazard, both risk and probe converge to the conservative `make` behavior: refresh every demand.

## 5. Next gate

Do not tune this simulator further.

The next useful experiment is a real-command workload where:

- exact local state is genuinely cheap to inspect;
- an external/opaque fact has a real paid check;
- refresh has a measured wall-clock or API cost;
- stale use has an operational consequence;
- async work has an actual completion time.

That is where Fusion1 can either become useful or collapse into ordinary conservative invalidation.
