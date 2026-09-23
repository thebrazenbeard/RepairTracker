from __future__ import annotations

from dataclasses import dataclass
import re

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


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class RuntimeArtifactClaim:
    service_id: str
    service_name: str
    service_namespace: str | None
    service_instance_id: str | None
    service_version: str | None
    deployment_environment: str | None
    artifact_name: str | None
    digest_algorithm: str
    digest: str
    source_attribute: str
    observed_at: str
    source_locator: str
    evidence: EvidencePointer
    deployment_id: str | None = None
    deployment_name: str | None = None

    @property
    def artifact_ref(self) -> str:
        return f"{self.digest_algorithm}:{self.digest}"

    @property
    def artifact_node_id(self) -> str:
        return f"artifact:{self.artifact_ref}"


@dataclass(frozen=True, slots=True)
class RuntimeArtifactResult:
    claims: tuple[RuntimeArtifactClaim, ...]
    bound_claims: int
    warnings: tuple[str, ...] = ()


def _service_id(span: OTelSpanObservation) -> str:
    return f"service:{span.service_namespace or ''}:{span.service_name}"


def _parse_sha256(value: str) -> str | None:
    prefix = "sha256:"
    text = value.strip()
    if not text.lower().startswith(prefix):
        return None
    digest = text[len(prefix):]
    if not _SHA256.fullmatch(digest):
        return None
    return digest.lower()


def _parse_repo_digest(value: str) -> tuple[str, str] | None:
    text = value.strip()
    if "@" not in text:
        return None
    name, digest_value = text.rsplit("@", 1)
    name = name.strip()
    if not name or any(ch.isspace() for ch in name):
        return None
    digest = _parse_sha256(digest_value)
    if digest is None:
        return None
    return name, digest


def extract_runtime_artifact_claims(
    spans: tuple[OTelSpanObservation, ...],
) -> tuple[tuple[RuntimeArtifactClaim, ...], tuple[str, ...]]:
    """Extract portable runtime artifact identities from OTel resource metadata.

    Repository digests and OCI manifest digests are portable identities.
    container.image.id is retained by telemetry but deliberately does not
    qualify as a portable artifact identity because OTel documents it as
    runtime-specific.
    """

    claims: list[RuntimeArtifactClaim] = []
    warnings: list[str] = []
    seen: set[
        tuple[
            str,
            str,
            str | None,
            str | None,
            str | None,
            str | None,
            str | None,
        ]
    ] = set()

    for span in spans:
        artifact_name: str | None = None
        digest: str | None = None
        source_attribute: str | None = None

        parsed_repo_digests: list[tuple[str, str]] = []
        for value in span.container_image_repo_digests:
            parsed = _parse_repo_digest(value)
            if parsed is None:
                warnings.append(
                    f"{span.trace_id}:{span.span_id} has invalid "
                    "container.image.repo_digests entry"
                )
                continue
            parsed_repo_digests.append(parsed)

        if parsed_repo_digests:
            unique_digests = {item[1] for item in parsed_repo_digests}
            if len(unique_digests) != 1:
                warnings.append(
                    f"{span.trace_id}:{span.span_id} reports conflicting "
                    "portable container repository digests; binding skipped"
                )
                continue
            digest = next(iter(unique_digests))
            if span.oci_manifest_digest is not None:
                manifest_digest = _parse_sha256(span.oci_manifest_digest)
                if manifest_digest is None:
                    warnings.append(
                        f"{span.trace_id}:{span.span_id} has invalid "
                        "oci.manifest.digest alongside repository digests; "
                        "binding skipped"
                    )
                    continue
                if manifest_digest != digest:
                    warnings.append(
                        f"{span.trace_id}:{span.span_id} reports conflicting "
                        "container repository and OCI manifest digests; "
                        "binding skipped"
                    )
                    continue

            repository_names = sorted({item[0] for item in parsed_repo_digests})
            if len(repository_names) == 1:
                artifact_name = repository_names[0]
            else:
                artifact_name = None
                warnings.append(
                    f"{span.trace_id}:{span.span_id} reports one portable "
                    "artifact digest under multiple repository names; digest "
                    "retained but artifact name is ambiguous"
                )
            source_attribute = "container.image.repo_digests"
        elif span.oci_manifest_digest is not None:
            digest = _parse_sha256(span.oci_manifest_digest)
            if digest is None:
                warnings.append(
                    f"{span.trace_id}:{span.span_id} has invalid "
                    "oci.manifest.digest"
                )
                continue
            artifact_name = span.container_image_name
            source_attribute = "oci.manifest.digest"
        elif span.container_image_id is not None:
            warnings.append(
                f"{span.trace_id}:{span.span_id} only reports "
                "container.image.id; runtime-specific identity is not used "
                "for portable artifact attestation binding"
            )
            continue
        else:
            continue

        service_id = _service_id(span)
        key = (
            service_id,
            digest,
            span.service_instance_id,
            span.deployment_environment,
            span.service_version,
            span.deployment_id,
            span.deployment_name,
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
            "artifact_name": artifact_name,
            "digest_algorithm": "sha256",
            "digest": digest,
            "source_attribute": source_attribute,
            "container_id": span.container_id,
            "deployment_id": span.deployment_id,
            "deployment_name": span.deployment_name,
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
            RuntimeArtifactClaim(
                service_id=service_id,
                service_name=span.service_name,
                service_namespace=span.service_namespace,
                service_instance_id=span.service_instance_id,
                service_version=span.service_version,
                deployment_environment=span.deployment_environment,
                artifact_name=artifact_name,
                digest_algorithm="sha256",
                digest=digest,
                source_attribute=source_attribute,
                observed_at=span.observed_at,
                source_locator=span.source_locator,
                evidence=evidence,
                deployment_id=span.deployment_id,
                deployment_name=span.deployment_name,
            )
        )

    return tuple(claims), tuple(warnings)


def apply_runtime_artifact_topology(
    topology: PortfolioTopology,
    spans: tuple[OTelSpanObservation, ...],
) -> RuntimeArtifactResult:
    claims, warnings = extract_runtime_artifact_claims(spans)
    bound = 0

    for claim in claims:
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
                node_id=claim.artifact_node_id,
                kind=NodeKind.ARTIFACT,
                label=claim.artifact_ref,
                attributes={
                    "digest_algorithm": claim.digest_algorithm,
                    "digest": claim.digest,
                    "portable_identity": True,
                },
                evidence=(claim.evidence,),
            )
        )

        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    claim.service_id,
                    claim.artifact_node_id,
                    RelationType.RUNS_ARTIFACT,
                    RelationDisposition.OBSERVED,
                    discriminator=(
                        f"{claim.service_instance_id or ''}:"
                        f"{claim.deployment_environment or ''}:"
                        f"{claim.service_version or ''}:"
                        f"{claim.artifact_ref}"
                    ),
                ),
                source_id=claim.service_id,
                target_id=claim.artifact_node_id,
                relation=RelationType.RUNS_ARTIFACT,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(claim.evidence,),
                attributes={
                    "service.instance.id": claim.service_instance_id,
                    "service.version": claim.service_version,
                    "deployment.environment.name": claim.deployment_environment,
                    "deployment.id": claim.deployment_id,
                    "deployment.name": claim.deployment_name,
                    "claim_ceiling": "RUNTIME_OBSERVED_PORTABLE_ARTIFACT_DIGEST",
                },
            )
        )
        bound += 1

    return RuntimeArtifactResult(
        claims=claims,
        bound_claims=bound,
        warnings=warnings,
    )
