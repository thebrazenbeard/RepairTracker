from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlparse

from .model import EvidenceClass, canonical_digest
from .telemetry import OTelSpanObservation
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


_HEX_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$")
_GITHUB_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class RevisionResolution:
    repository_id: str
    requested_revision: str
    resolved_revision: str
    observed_at: str
    locator: str


class RevisionResolver(Protocol):
    def resolve_revision(
        self, repository_id: str, revision: str
    ) -> RevisionResolution: ...


@dataclass(frozen=True, slots=True)
class RuntimeSourceClaim:
    service_id: str
    service_name: str
    service_namespace: str | None
    service_instance_id: str | None
    service_version: str | None
    deployment_environment: str | None
    repository_id: str
    repository_url: str
    claimed_revision: str
    observed_at: str
    source_locator: str
    evidence: EvidencePointer


@dataclass(frozen=True, slots=True)
class RuntimeBindingResult:
    claims: tuple[RuntimeSourceClaim, ...]
    bound_claims: int
    warnings: tuple[str, ...] = ()


def github_repository_id_from_url(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        return None
    if (parsed.hostname or "").lower() != "github.com":
        return None
    if parsed.port is not None or parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment or parsed.params:
        return None

    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(_GITHUB_COMPONENT.fullmatch(part) for part in parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def _service_id(span: OTelSpanObservation) -> str:
    return f"service:{span.service_namespace or ''}:{span.service_name}"


def extract_runtime_source_claims(
    spans: tuple[OTelSpanObservation, ...],
) -> tuple[tuple[RuntimeSourceClaim, ...], tuple[str, ...]]:
    claims: list[RuntimeSourceClaim] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str, str | None, str | None]] = set()

    for span in spans:
        if span.vcs_repository_url is None and span.vcs_revision is None:
            continue
        if span.vcs_repository_url is None or span.vcs_revision is None:
            warnings.append(
                f"{span.trace_id}:{span.span_id} has incomplete VCS source metadata"
            )
            continue

        repository_id = github_repository_id_from_url(span.vcs_repository_url)
        if repository_id is None:
            warnings.append(
                f"{span.trace_id}:{span.span_id} has unsupported/non-canonical "
                "GitHub repository URL"
            )
            continue
        if not _HEX_REVISION.fullmatch(span.vcs_revision):
            warnings.append(
                f"{span.trace_id}:{span.span_id} reports symbolic/non-exact "
                f"VCS revision {span.vcs_revision!r}; exact binding skipped"
            )
            continue

        service_id = _service_id(span)
        key = (
            service_id,
            repository_id.lower(),
            span.vcs_revision.lower(),
            span.service_instance_id,
            span.deployment_environment,
        )
        if key in seen:
            continue
        seen.add(key)

        payload = {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "service_id": service_id,
            "service_instance_id": span.service_instance_id,
            "service_version": span.service_version,
            "deployment_environment": span.deployment_environment,
            "repository_id": repository_id,
            "repository_url": span.vcs_repository_url,
            "claimed_revision": span.vcs_revision.lower(),
        }
        evidence = EvidencePointer(
            source_system="opentelemetry",
            locator=span.source_locator,
            subject_ref=f"{span.trace_id}:{span.span_id}",
            observed_at=span.observed_at,
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest=canonical_digest(payload),
        )
        claims.append(
            RuntimeSourceClaim(
                service_id=service_id,
                service_name=span.service_name,
                service_namespace=span.service_namespace,
                service_instance_id=span.service_instance_id,
                service_version=span.service_version,
                deployment_environment=span.deployment_environment,
                repository_id=repository_id,
                repository_url=span.vcs_repository_url,
                claimed_revision=span.vcs_revision.lower(),
                observed_at=span.observed_at,
                source_locator=span.source_locator,
                evidence=evidence,
            )
        )

    return tuple(claims), tuple(warnings)


def bind_runtime_sources(
    topology: PortfolioTopology,
    spans: tuple[OTelSpanObservation, ...],
    resolver: RevisionResolver,
) -> RuntimeBindingResult:
    """Bind runtime source claims without pretending telemetry proves provenance.

    The SERVICE -> SOURCE_REVISION edge means the runtime reported that source.
    The SOURCE_REVISION -> REPOSITORY edge independently verifies only that the
    resolved commit belongs to that repository. Build/deployment attestation is
    still required to prove that the running artifact was produced from it.
    """

    claims, warnings = extract_runtime_source_claims(spans)
    warning_list = list(warnings)
    bound = 0

    for claim in claims:
        repository_node_id = f"repo:{claim.repository_id}"
        if repository_node_id not in topology.nodes:
            warning_list.append(
                f"runtime source claim references repository outside observed "
                f"portfolio: {claim.repository_id}"
            )
            continue

        resolution = resolver.resolve_revision(
            claim.repository_id, claim.claimed_revision
        )
        if resolution.repository_id.lower() != claim.repository_id.lower():
            raise ValueError("revision resolver returned a different repository")
        if not resolution.resolved_revision.lower().startswith(
            claim.claimed_revision.lower()
        ):
            raise ValueError(
                "resolved revision does not match claimed immutable revision prefix"
            )

        exact_revision = resolution.resolved_revision.lower()
        source_node_id = f"source:{claim.repository_id}@{exact_revision}"

        topology.add_node(
            TopologyNode(
                node_id=claim.service_id,
                kind=NodeKind.SERVICE,
                label=claim.service_name,
                attributes={"service.namespace": claim.service_namespace},
                evidence=(claim.evidence,),
            )
        )
        topology.add_node(
            TopologyNode(
                node_id=source_node_id,
                kind=NodeKind.SOURCE_REVISION,
                label=f"{claim.repository_id}@{exact_revision}",
                attributes={
                    "repository_id": claim.repository_id,
                    "revision": exact_revision,
                },
                evidence=(claim.evidence,),
            )
        )

        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    claim.service_id,
                    source_node_id,
                    RelationType.REPORTS_SOURCE,
                    RelationDisposition.OBSERVED,
                    discriminator=(
                        f"{claim.service_instance_id or ''}:"
                        f"{claim.deployment_environment or ''}:"
                        f"{claim.claimed_revision}"
                    ),
                ),
                source_id=claim.service_id,
                target_id=source_node_id,
                relation=RelationType.REPORTS_SOURCE,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(claim.evidence,),
                attributes={
                    "service.instance.id": claim.service_instance_id,
                    "service.version": claim.service_version,
                    "deployment.environment.name": claim.deployment_environment,
                    "claim_ceiling": "RUNTIME_SELF_REPORTED_SOURCE",
                },
            )
        )

        resolution_evidence = EvidencePointer(
            source_system="github-rest",
            locator=resolution.locator,
            subject_ref=exact_revision,
            observed_at=resolution.observed_at,
            evidence_class=EvidenceClass.VERIFIED,
            payload_digest=canonical_digest(
                {
                    "repository_id": resolution.repository_id,
                    "requested_revision": resolution.requested_revision,
                    "resolved_revision": exact_revision,
                }
            ),
        )
        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    source_node_id,
                    repository_node_id,
                    RelationType.BELONGS_TO,
                    RelationDisposition.VERIFIED,
                    discriminator=exact_revision,
                ),
                source_id=source_node_id,
                target_id=repository_node_id,
                relation=RelationType.BELONGS_TO,
                disposition=RelationDisposition.VERIFIED,
                confidence=1.0,
                evidence=(resolution_evidence,),
                verification_ref=(
                    f"github-commit://{claim.repository_id}@{exact_revision}"
                ),
                attributes={
                    "verification_ceiling": "SOURCE_REVISION_EXISTS_IN_REPOSITORY"
                },
            )
        )
        bound += 1

    return RuntimeBindingResult(
        claims=claims,
        bound_claims=bound,
        warnings=tuple(warning_list),
    )
