from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable


class EvidenceClass(StrEnum):
    USER_DIRECT = "USER_DIRECT"
    OBSERVED = "OBSERVED"
    RETRIEVED_EVIDENCE = "RETRIEVED_EVIDENCE"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"


class Severity(StrEnum):
    SEV_0 = "SEV-0"
    SEV_1 = "SEV-1"
    SEV_2 = "SEV-2"
    SEV_3 = "SEV-3"


class IncidentState(StrEnum):
    DETECTED = "DETECTED"
    ACTIVE = "ACTIVE"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class RepairAttemptState(StrEnum):
    PROPOSED = "PROPOSED"
    REPRODUCING = "REPRODUCING"
    DIAGNOSING = "DIAGNOSING"
    PLANNED = "PLANNED"
    BUILDING = "BUILDING"
    REVIEWING = "REVIEWING"
    READY = "READY"
    EFFECT_PENDING = "EFFECT_PENDING"
    VERIFYING = "VERIFYING"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class EffectState(StrEnum):
    PREPARED = "PREPARED"
    ATTEMPTED = "ATTEMPTED"
    OBSERVED_APPLIED = "OBSERVED_APPLIED"
    OBSERVED_NOT_APPLIED = "OBSERVED_NOT_APPLIED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECONCILED = "RECONCILED"


INCIDENT_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    IncidentState.DETECTED: frozenset({IncidentState.ACTIVE}),
    IncidentState.ACTIVE: frozenset({IncidentState.MITIGATED, IncidentState.RESOLVED}),
    IncidentState.MITIGATED: frozenset({IncidentState.ACTIVE, IncidentState.RESOLVED}),
    IncidentState.RESOLVED: frozenset({IncidentState.MONITORING, IncidentState.ACTIVE}),
    IncidentState.MONITORING: frozenset({IncidentState.CLOSED, IncidentState.ACTIVE}),
    IncidentState.CLOSED: frozenset(),
}

ATTEMPT_TRANSITIONS: dict[RepairAttemptState, frozenset[RepairAttemptState]] = {
    RepairAttemptState.PROPOSED: frozenset({
        RepairAttemptState.REPRODUCING,
        RepairAttemptState.DIAGNOSING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.REPRODUCING: frozenset({
        RepairAttemptState.DIAGNOSING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.DIAGNOSING: frozenset({
        RepairAttemptState.PLANNED,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.PLANNED: frozenset({
        RepairAttemptState.BUILDING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.BUILDING: frozenset({
        RepairAttemptState.REVIEWING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.REVIEWING: frozenset({
        RepairAttemptState.BUILDING,
        RepairAttemptState.READY,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.READY: frozenset({
        RepairAttemptState.EFFECT_PENDING,
        RepairAttemptState.VERIFYING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.EFFECT_PENDING: frozenset({
        RepairAttemptState.VERIFYING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.VERIFYING: frozenset({
        RepairAttemptState.QUALIFIED,
        RepairAttemptState.FAILED,
        RepairAttemptState.BUILDING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.QUALIFIED: frozenset(),
    RepairAttemptState.FAILED: frozenset(),
    RepairAttemptState.SUPERSEDED: frozenset(),
}

EFFECT_TRANSITIONS: dict[EffectState, frozenset[EffectState]] = {
    EffectState.PREPARED: frozenset({EffectState.ATTEMPTED}),
    EffectState.ATTEMPTED: frozenset({
        EffectState.OBSERVED_APPLIED,
        EffectState.OBSERVED_NOT_APPLIED,
        EffectState.OUTCOME_UNKNOWN,
    }),
    EffectState.OBSERVED_APPLIED: frozenset({EffectState.RECONCILED}),
    EffectState.OBSERVED_NOT_APPLIED: frozenset({EffectState.RECONCILED}),
    EffectState.OUTCOME_UNKNOWN: frozenset({EffectState.RECONCILED}),
    EffectState.RECONCILED: frozenset(),
}


class TransitionError(ValueError):
    pass


def require_transition(current: StrEnum, successor: StrEnum, table: dict) -> None:
    allowed = table.get(current, frozenset())
    if successor not in allowed:
        raise TransitionError(f"invalid transition: {current} -> {successor}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RepairEvent:
    event_id: str
    repair_id: str
    event_type: str
    subject_id: str
    evidence_class: EvidenceClass
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_system: str = "repairtracker"
    source_subject: str | None = None
    event_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observed_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    predecessor_digest: str | None = None
    authority_or_effect_ceiling: str = "OBSERVE_ONLY"
    trace_correlation: str | None = None

    def body(self) -> dict[str, Any]:
        body = asdict(self)
        body["evidence_class"] = self.evidence_class.value
        return body

    @property
    def digest(self) -> str:
        return canonical_digest(self.body())


class EventLog:
    """Append-only, digest-chained RepairEvent collection."""

    def __init__(self, events: Iterable[RepairEvent] = ()) -> None:
        self._events: list[RepairEvent] = []
        for event in events:
            self.append(event)

    @property
    def events(self) -> tuple[RepairEvent, ...]:
        return tuple(self._events)

    @property
    def head_digest(self) -> str | None:
        return self._events[-1].digest if self._events else None

    def append(self, event: RepairEvent) -> None:
        expected = self.head_digest
        if event.predecessor_digest != expected:
            raise ValueError(
                f"event predecessor mismatch: expected {expected!r}, "
                f"got {event.predecessor_digest!r}"
            )
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        self._events.append(event)
