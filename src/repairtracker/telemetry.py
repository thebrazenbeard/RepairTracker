from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .model import EvidenceClass, RepairEvent, canonical_digest
from .topology import (
    EvidencePointer,
    NodeKind,
    PortfolioTopology,
    RelationDisposition,
    RelationType,
    TopologyEdge,
    TopologyNode,
    topology_edge_id,
)


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


@dataclass(frozen=True, slots=True)
class OTelSpanObservation:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service_name: str
    service_namespace: str | None
    span_name: str
    observed_at: str
    source_locator: str

    def __post_init__(self) -> None:
        if not _TRACE_ID.fullmatch(self.trace_id) or set(self.trace_id) == {"0"}:
            raise ValueError("OTel span trace_id must be 32 non-zero lowercase hex")
        if not _SPAN_ID.fullmatch(self.span_id) or set(self.span_id) == {"0"}:
            raise ValueError("OTel span span_id must be 16 non-zero lowercase hex")
        if self.parent_span_id is not None:
            if (
                not _SPAN_ID.fullmatch(self.parent_span_id)
                or set(self.parent_span_id) == {"0"}
            ):
                raise ValueError("OTel parent_span_id must be 16 non-zero lowercase hex")
        if not self.service_name.strip():
            raise ValueError("OTel service_name is required")


@dataclass(frozen=True, slots=True)
class OTelExtractionResult:
    spans: tuple[OTelSpanObservation, ...]
    warnings: tuple[str, ...] = ()


def _otel_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key in value:
            return value[key]
    return None


def _otel_attributes(items: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        if not isinstance(key, str):
            continue
        result[key] = _otel_value(item.get("value"))
    return result


def extract_otlp_json_spans(
    payload: Mapping[str, Any],
    *,
    observed_at: str,
    source_locator: str,
    max_spans: int = 50_000,
) -> OTelExtractionResult:
    """Extract normalized spans from OTLP/JSON TracesData without executing input."""

    if max_spans < 1:
        raise ValueError("max_spans must be positive")

    spans: list[OTelSpanObservation] = []
    warnings: list[str] = []

    resource_spans = payload.get("resourceSpans", [])
    if not isinstance(resource_spans, list):
        raise ValueError("OTLP JSON resourceSpans must be a list")

    for resource_index, resource_group in enumerate(resource_spans):
        if not isinstance(resource_group, Mapping):
            continue
        resource = resource_group.get("resource", {})
        resource_attrs = _otel_attributes(
            resource.get("attributes", []) if isinstance(resource, Mapping) else []
        )
        service_name = resource_attrs.get("service.name")
        namespace = resource_attrs.get("service.namespace")
        if not isinstance(service_name, str) or not service_name.strip():
            warnings.append(
                f"resourceSpans[{resource_index}] missing service.name; spans skipped"
            )
            continue
        service_name = service_name.strip()
        if isinstance(namespace, str):
            namespace = namespace.strip() or None
        else:
            namespace = None

        scope_spans = resource_group.get("scopeSpans", [])
        if not isinstance(scope_spans, list):
            continue
        for scope_group in scope_spans:
            if not isinstance(scope_group, Mapping):
                continue
            raw_spans = scope_group.get("spans", [])
            if not isinstance(raw_spans, list):
                continue
            for raw in raw_spans:
                if not isinstance(raw, Mapping):
                    continue
                if len(spans) >= max_spans:
                    warnings.append(
                        "OTLP span limit reached; topology evidence may be incomplete"
                    )
                    return OTelExtractionResult(tuple(spans), tuple(warnings))

                trace_id = raw.get("traceId")
                span_id = raw.get("spanId")
                parent_span_id = raw.get("parentSpanId") or None
                span_name = raw.get("name")
                if not all(isinstance(item, str) for item in (trace_id, span_id, span_name)):
                    warnings.append("OTLP span missing traceId/spanId/name; span skipped")
                    continue
                try:
                    spans.append(
                        OTelSpanObservation(
                            trace_id=trace_id.lower(),
                            span_id=span_id.lower(),
                            parent_span_id=(
                                parent_span_id.lower()
                                if isinstance(parent_span_id, str)
                                else None
                            ),
                            service_name=service_name,
                            service_namespace=namespace,
                            span_name=span_name,
                            observed_at=observed_at,
                            source_locator=source_locator,
                        )
                    )
                except ValueError as exc:
                    warnings.append(f"invalid OTLP span skipped: {exc}")

    return OTelExtractionResult(tuple(spans), tuple(warnings))


def _service_id(span: OTelSpanObservation) -> str:
    namespace = span.service_namespace or ""
    return f"service:{namespace}:{span.service_name}"


def apply_otel_service_topology(
    topology: PortfolioTopology,
    spans: tuple[OTelSpanObservation, ...],
) -> int:
    """Add observed cross-service parent/child calls from one normalized span set.

    These are observations of calls that occurred, not permanent DEPENDS_ON
    claims and not VERIFIED relations.
    """

    span_index: dict[tuple[str, str], OTelSpanObservation] = {}
    for span in spans:
        key = (span.trace_id, span.span_id)
        if key in span_index:
            raise ValueError(
                "duplicate OTLP span identity: "
                f"{span.trace_id}:{span.span_id}"
            )
        span_index[key] = span

    for span in spans:
        evidence = EvidencePointer(
            source_system="opentelemetry",
            locator=span.source_locator,
            subject_ref=f"{span.trace_id}:{span.span_id}",
            observed_at=span.observed_at,
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest=canonical_digest(
                {
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "parent_span_id": span.parent_span_id,
                    "service_name": span.service_name,
                    "service_namespace": span.service_namespace,
                    "span_name": span.span_name,
                }
            ),
        )
        topology.add_node(
            TopologyNode(
                node_id=_service_id(span),
                kind=NodeKind.SERVICE,
                label=span.service_name,
                attributes={"service.namespace": span.service_namespace},
                evidence=(evidence,),
            )
        )

    added = 0
    for child in spans:
        if child.parent_span_id is None:
            continue
        parent = span_index.get((child.trace_id, child.parent_span_id))
        if parent is None:
            continue
        source_id = _service_id(parent)
        target_id = _service_id(child)
        if source_id == target_id:
            continue

        parent_evidence = EvidencePointer(
            source_system="opentelemetry",
            locator=parent.source_locator,
            subject_ref=f"{parent.trace_id}:{parent.span_id}",
            observed_at=parent.observed_at,
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest=canonical_digest(
                {
                    "trace_id": parent.trace_id,
                    "span_id": parent.span_id,
                    "service_name": parent.service_name,
                    "service_namespace": parent.service_namespace,
                    "span_name": parent.span_name,
                }
            ),
        )
        child_evidence = EvidencePointer(
            source_system="opentelemetry",
            locator=child.source_locator,
            subject_ref=f"{child.trace_id}:{child.span_id}",
            observed_at=child.observed_at,
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest=canonical_digest(
                {
                    "trace_id": child.trace_id,
                    "span_id": child.span_id,
                    "parent_span_id": child.parent_span_id,
                    "service_name": child.service_name,
                    "service_namespace": child.service_namespace,
                    "span_name": child.span_name,
                }
            ),
        )
        edge = TopologyEdge(
            edge_id=topology_edge_id(
                source_id,
                target_id,
                RelationType.CALLS,
                RelationDisposition.OBSERVED,
                discriminator=f"{child.trace_id}:{parent.span_id}:{child.span_id}",
            ),
            source_id=source_id,
            target_id=target_id,
            relation=RelationType.CALLS,
            disposition=RelationDisposition.OBSERVED,
            confidence=1.0,
            evidence=(parent_evidence, child_evidence),
            attributes={
                "trace_id": child.trace_id,
                "parent_span_id": parent.span_id,
                "child_span_id": child.span_id,
            },
        )
        topology.add_edge(edge)
        added += 1

    return added


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
