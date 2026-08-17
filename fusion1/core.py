from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping


class Action(str, Enum):
    REUSE = "REUSE"
    WAIT = "WAIT"
    PROBE = "PROBE"
    WAKE = "WAKE"
    HOLD = "HOLD"


@dataclass
class Budget:
    """Token-bucket budget for probe/compute admission."""

    capacity: float
    refill_per_second: float = 0.0
    balance: float | None = None
    last_time: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity < 0 or self.refill_per_second < 0:
            raise ValueError("budget values must be non-negative")
        if self.balance is None:
            self.balance = self.capacity
        self.balance = min(self.capacity, max(0.0, float(self.balance)))

    def _refill(self, now: float) -> None:
        if now < self.last_time:
            raise ValueError("time cannot move backwards")
        elapsed = now - self.last_time
        self.balance = min(
            self.capacity,
            float(self.balance) + elapsed * self.refill_per_second,
        )
        self.last_time = now

    def can_spend(self, cost: float, now: float) -> bool:
        self._refill(now)
        return float(self.balance) + 1e-12 >= cost

    def spend(self, cost: float, now: float) -> bool:
        if cost < 0:
            raise ValueError("cost must be non-negative")
        if not self.can_spend(cost, now):
            return False
        self.balance = float(self.balance) - cost
        return True


@dataclass(frozen=True)
class SourceState:
    value: Any
    version: int
    observed_at: float


ComputeFn = Callable[[Mapping[str, Any]], Any]
ProbeFn = Callable[[Any, float], bool]


@dataclass(frozen=True)
class NodeSpec:
    name: str
    compute: ComputeFn
    dependencies: tuple[str, ...] = ()
    compute_cost: float = 1.0
    probe: ProbeFn | None = None
    probe_cost: float = 0.0
    hazard_per_second: float = 0.0
    reuse_threshold: float = 0.82

    def __post_init__(self) -> None:
        if self.compute_cost < 0 or self.probe_cost < 0 or self.hazard_per_second < 0:
            raise ValueError("costs and hazard must be non-negative")
        if not 0.0 <= self.reuse_threshold <= 1.0:
            raise ValueError("reuse_threshold must be in [0, 1]")


@dataclass
class CacheEntry:
    value: Any
    created_at: float
    dependency_versions: dict[str, int]
    generation: int


@dataclass
class PendingWork:
    value: Any
    ready_at: float
    dependency_versions: dict[str, int]
    generation: int


@dataclass(frozen=True)
class Decision:
    node: str
    action: Action
    value: Any
    cost: float
    reason: str
    p_valid: float | None
    generation: int | None


class Conductor:
    """Persistent inference admission control over a dependency graph.

    Fusion1 deliberately separates cheap control-plane decisions from expensive
    data-plane computation. Nodes may be reused, probed, woken, held for budget,
    or waited on when equivalent work is already in flight.
    """

    def __init__(self, *, budget: Budget | None = None) -> None:
        self.budget = budget
        self.sources: dict[str, SourceState] = {}
        self.nodes: dict[str, NodeSpec] = {}
        self.cache: dict[str, CacheEntry] = {}
        self.pending: dict[str, PendingWork] = {}
        self.events: list[dict[str, Any]] = []
        self.total_cost = 0.0
        self._generation = 0

    def register_source(self, name: str, value: Any, *, now: float = 0.0) -> None:
        if name in self.nodes:
            raise ValueError(f"{name!r} is already a node")
        self.sources[name] = SourceState(value=value, version=1, observed_at=now)

    def update_source(self, name: str, value: Any, *, now: float) -> None:
        old = self.sources.get(name)
        if old is None:
            self.register_source(name, value, now=now)
            return
        self.sources[name] = SourceState(
            value=value,
            version=old.version + 1,
            observed_at=now,
        )

    def register_node(self, spec: NodeSpec) -> None:
        if spec.name in self.sources:
            raise ValueError(f"{spec.name!r} is already a source")
        unknown = [d for d in spec.dependencies if d not in self.sources and d not in self.nodes]
        if unknown:
            raise KeyError(f"register dependencies before node {spec.name!r}: {unknown}")
        self.nodes[spec.name] = spec

    def start_pending(
        self,
        name: str,
        value: Any,
        *,
        ready_at: float,
        dependency_versions: Mapping[str, int] | None = None,
    ) -> None:
        if name not in self.nodes:
            raise KeyError(name)
        self._generation += 1
        self.pending[name] = PendingWork(
            value=value,
            ready_at=ready_at,
            dependency_versions=dict(dependency_versions or {}),
            generation=self._generation,
        )

    def _version_of(self, name: str) -> int:
        if name in self.sources:
            return self.sources[name].version
        if name in self.cache:
            return self.cache[name].generation
        return 0

    def _admit_cost(self, cost: float, now: float) -> bool:
        if self.budget is not None and not self.budget.spend(cost, now):
            return False
        self.total_cost += cost
        return True

    def _log(self, decision: Decision, now: float) -> None:
        record = {
            "time": now,
            "node": decision.node,
            "action": decision.action.value,
            "cost": decision.cost,
            "reason": decision.reason,
            "p_valid": decision.p_valid,
            "generation": decision.generation,
        }
        self.events.append(record)

    def _hold(self, name: str, *, now: float, reason: str, p_valid: float | None) -> Decision:
        entry = self.cache.get(name)
        decision = Decision(
            node=name,
            action=Action.HOLD,
            value=entry.value if entry else None,
            cost=0.0,
            reason=reason,
            p_valid=p_valid,
            generation=entry.generation if entry else None,
        )
        self._log(decision, now)
        return decision

    def resolve(self, name: str, *, now: float) -> Decision:
        if name in self.sources:
            src = self.sources[name]
            return Decision(name, Action.REUSE, src.value, 0.0, "recorded_source", 1.0, src.version)
        if name not in self.nodes:
            raise KeyError(name)

        spec = self.nodes[name]

        pending = self.pending.get(name)
        if pending is not None:
            if now < pending.ready_at:
                old = self.cache.get(name)
                decision = Decision(
                    node=name,
                    action=Action.WAIT,
                    value=old.value if old else None,
                    cost=0.0,
                    reason="equivalent_work_in_flight",
                    p_valid=None,
                    generation=old.generation if old else None,
                )
                self._log(decision, now)
                return decision
            self.cache[name] = CacheEntry(
                value=pending.value,
                created_at=now,
                dependency_versions=dict(pending.dependency_versions),
                generation=pending.generation,
            )
            del self.pending[name]
            decision = Decision(
                node=name,
                action=Action.REUSE,
                value=pending.value,
                cost=0.0,
                reason="pending_work_completed",
                p_valid=1.0,
                generation=pending.generation,
            )
            self._log(decision, now)
            return decision

        dep_values: dict[str, Any] = {}
        dep_versions: dict[str, int] = {}
        for dep in spec.dependencies:
            dep_decision = self.resolve(dep, now=now)
            if dep_decision.action in {Action.WAIT, Action.HOLD} and dep_decision.value is None:
                decision = Decision(
                    node=name,
                    action=Action.WAIT,
                    value=self.cache[name].value if name in self.cache else None,
                    cost=0.0,
                    reason=f"dependency_{dep_decision.action.value.lower()}:{dep}",
                    p_valid=None,
                    generation=self.cache[name].generation if name in self.cache else None,
                )
                self._log(decision, now)
                return decision
            dep_values[dep] = dep_decision.value
            dep_versions[dep] = self._version_of(dep)

        entry = self.cache.get(name)
        p_valid = 0.0
        deps_match = False
        if entry is not None:
            deps_match = entry.dependency_versions == dep_versions
            if deps_match:
                age = max(0.0, now - entry.created_at)
                p_valid = math.exp(-spec.hazard_per_second * age)

        if entry is not None and deps_match and p_valid >= spec.reuse_threshold:
            decision = Decision(
                node=name,
                action=Action.REUSE,
                value=entry.value,
                cost=0.0,
                reason="cached_result_still_valid",
                p_valid=p_valid,
                generation=entry.generation,
            )
            self._log(decision, now)
            return decision

        if entry is not None and deps_match and spec.probe is not None and spec.probe_cost < spec.compute_cost:
            if not self._admit_cost(spec.probe_cost, now):
                return self._hold(name, now=now, reason="probe_budget_denied", p_valid=p_valid)
            still_valid = bool(spec.probe(entry.value, now))
            if still_valid:
                entry.created_at = now
                decision = Decision(
                    node=name,
                    action=Action.PROBE,
                    value=entry.value,
                    cost=spec.probe_cost,
                    reason="cheap_probe_confirmed_cache",
                    p_valid=1.0,
                    generation=entry.generation,
                )
                self._log(decision, now)
                return decision

        if not self._admit_cost(spec.compute_cost, now):
            return self._hold(name, now=now, reason="compute_budget_denied", p_valid=p_valid)

        value = spec.compute(dep_values)
        self._generation += 1
        new_entry = CacheEntry(
            value=value,
            created_at=now,
            dependency_versions=dep_versions,
            generation=self._generation,
        )
        self.cache[name] = new_entry
        decision = Decision(
            node=name,
            action=Action.WAKE,
            value=value,
            cost=spec.compute_cost,
            reason=("dependency_changed" if entry is not None and not deps_match else "cache_missing_or_invalid"),
            p_valid=1.0,
            generation=new_entry.generation,
        )
        self._log(decision, now)
        return decision

    def metrics(self) -> dict[str, Any]:
        counts = {action.value: 0 for action in Action}
        for event in self.events:
            counts[event["action"]] += 1
        return {
            "total_cost": self.total_cost,
            "events": len(self.events),
            "actions": counts,
            "cached_nodes": len(self.cache),
            "pending_nodes": len(self.pending),
            "budget_balance": None if self.budget is None else self.budget.balance,
        }

    def write_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        with path.open("w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event, sort_keys=True) + "\n")
