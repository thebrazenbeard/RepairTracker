from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .model import RepairEvent


_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-"
    r"(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-"
    r"(?P<flags>[0-9a-f]{2})$"
)


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: int = 1

    def __post_init__(self) -> None:
        if not _TRACE_ID.fullmatch(self.trace_id) or set(self.trace_id) == {"0"}:
            raise ValueError("trace_id must be 32 lowercase non-zero hex characters")
        if not _SPAN_ID.fullmatch(self.span_id) or set(self.span_id) == {"0"}:
            raise ValueError("span_id must be 16 lowercase non-zero hex characters")
        if not 0 <= self.trace_flags <= 255:
            raise ValueError("trace_flags must fit in one byte")

    @classmethod
    def from_traceparent(cls, value: str) -> "TraceContext":
        match = _TRACEPARENT.fullmatch(value.strip().lower())
        if not match:
            raise ValueError("invalid W3C traceparent")
        version = match.group("version")
        if version != "00":
            raise ValueError("V0 supports W3C traceparent version 00 only")
        return cls(
            trace_id=match.group("trace_id"),
            span_id=match.group("span_id"),
            trace_flags=int(match.group("flags"), 16),
        )

    @property
    def traceparent(self) -> str:
        return (
            f"00-{self.trace_id}-{self.span_id}-"
            f"{self.trace_flags:02x}"
        )


def repair_event_to_otel_event(
    event: RepairEvent,
    trace: TraceContext | None = None,
    service_name: str = "repairtracker",
) -> dict[str, Any]:
    """Create an OpenTelemetry-compatible event record.

    This is a semantic event representation, not an OTLP protobuf exporter.
    The event name is deliberately low-cardinality; dynamic repair details are
    attributes.
    """

    record: dict[str, Any] = {
        "event_name": "repairtracker.repair.event",
        "timestamp": event.event_time,
        "observed_timestamp": event.observed_time,
        "resource": {"service.name": service_name},
        "attributes": {
            "repairtracker.repair.id": event.repair_id,
            "repairtracker.subject.id": event.subject_id,
            "repairtracker.event.id": event.event_id,
            "repairtracker.event.type": event.event_type,
            "repairtracker.evidence.class": event.evidence_class.value,
            "repairtracker.source.system": event.source_system,
            "repairtracker.authority_effect_ceiling": (
                event.authority_or_effect_ceiling
            ),
            "repairtracker.event.digest": event.digest,
        },
    }
    if event.source_subject is not None:
        record["attributes"]["repairtracker.source.subject"] = event.source_subject
    if trace is not None:
        record["trace_id"] = trace.trace_id
        record["span_id"] = trace.span_id
        record["trace_flags"] = trace.trace_flags
    return record
