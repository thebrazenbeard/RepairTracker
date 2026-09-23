from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .model import EvidenceClass, canonical_digest
from .runtime_binding import RevisionResolver, github_repository_id_from_url
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


SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HEX_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$")


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
    repository_id: str | None = None
    claimed_revision: str | None = None
    deployment_id: str | None = None
    deployment_name: str | None = None

    @property
    def artifact_ref(self) -> str:
        return f"{self.digest_algorithm}:{self.digest}"

    @property
    def artifact_node_id(self) -> str:
        return f"artifact:{self.artifact_ref}"

    @property
    def artifact_reference(self) -> str | None:
        if not self.artifact_name:
            return None
        return f"oci://{self.artifact_name}@{self.artifact_ref}"


@dataclass(frozen=True, slots=True)
class RuntimeArtifactResult:
    claims: tuple[RuntimeArtifactClaim, ...]
    bound_claims: int
    warnings: tuple[str, ...] = ()


def _service_id(span: OTelSpanObservation) -> str:
    return f"service:{span.service_namespace or ''}:{span.service_name}"


def normalize_sha256_digest(value: str) -> str | None:
    text = value.strip()
    if text.lower().startswith("sha256:"):
        text = text[len("sha256:"):]
    if not _SHA256.fullmatch(text):
        return None
    return f"sha256:{text.lower()}"


def _parse_sha256(value: str) -> str | None:
    normalized = normalize_sha256_digest(value)
    return normalized.split(":", 1)[1] if normalized is not None else None


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
        tuple[str, str, str | None, str | None, str | None]
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
                        "oci.manifest.digest alongside repository digest; binding skipped"
                    )
                    continue
                if manifest_digest != digest:
                    warnings.append(
                        f"{span.trace_id}:{span.span_id} reports conflicting "
                        "repository and OCI manifest digests; binding skipped"
                    )
                    continue
            repository_names = sorted({item[0] for item in parsed_repo_digests})
            if len(repository_names) == 1:
                artifact_name = repository_names[0]
            else:
                artifact_name = None
                warnings.append(
                    f"{span.trace_id}:{span.span_id} reports one portable digest "
                    "under multiple repository names; digest retained but OCI "
                    "verification reference is ambiguous"
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
        repository_id = (
            github_repository_id_from_url(span.vcs_repository_url)
            if span.vcs_repository_url is not None
            else None
        )
        claimed_revision = (
            span.vcs_revision.lower()
            if isinstance(span.vcs_revision, str)
            else None
        )
        key = (
            service_id,
            digest,
            span.service_instance_id,
            span.deployment_environment,
            span.service_version,
            repository_id,
            claimed_revision,
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
            "repository_id": repository_id,
            "claimed_revision": claimed_revision,
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
                repository_id=repository_id,
                claimed_revision=claimed_revision,
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


@dataclass(frozen=True, slots=True)
class VerifiedArtifactProvenance:
    artifact_digest: str
    repository_id: str
    source_revision: str
    predicate_type: str
    verifier: str
    verification_ref: str
    observed_at: str
    receipt_digest: str
    signer_identity: str | None = None


class ArtifactAttestationVerifier(Protocol):
    def verify(
        self,
        *,
        artifact_reference: str,
        artifact_digest: str,
        repository_id: str,
        source_revision: str,
    ) -> VerifiedArtifactProvenance: ...


@dataclass(frozen=True, slots=True)
class AttestedArtifactResult:
    claims: tuple[RuntimeArtifactClaim, ...]
    verified_bindings: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedArtifactDeploymentRecord:
    source_system: str
    record_id: str
    artifact_digest: str
    logical_environment: str | None
    physical_environment: str | None
    cluster: str | None
    deployment_name: str | None
    attestation_id: str | None
    created_at: str | None
    updated_at: str | None
    locator: str
    observed_at: str
    payload_digest: str


def bind_attested_runtime_artifacts(
    topology: PortfolioTopology,
    spans: tuple[OTelSpanObservation, ...],
    revision_resolver: RevisionResolver,
    attestation_verifier: ArtifactAttestationVerifier,
) -> AttestedArtifactResult:
    """Compose runtime artifact observation with cryptographic build provenance."""

    claims, warnings = extract_runtime_artifact_claims(spans)
    warning_list = list(warnings)
    verified = 0

    for claim in claims:
        if claim.service_instance_id is None:
            warning_list.append(
                f"{claim.service_id}/{claim.artifact_ref} has no "
                "service.instance.id; attested runtime binding skipped"
            )
            continue
        if claim.repository_id is None or claim.claimed_revision is None:
            warning_list.append(
                f"{claim.service_id}/{claim.artifact_ref} has no canonical "
                "repository/revision source claim; attestation binding skipped"
            )
            continue
        if not _HEX_REVISION.fullmatch(claim.claimed_revision):
            warning_list.append(
                f"{claim.service_id}/{claim.artifact_ref} reports symbolic/non-exact "
                f"VCS revision {claim.claimed_revision!r}; attestation binding skipped"
            )
            continue
        if claim.artifact_reference is None:
            warning_list.append(
                f"{claim.service_id}/{claim.artifact_ref} has no immutable OCI "
                "artifact reference; attestation binding skipped"
            )
            continue

        repository_matches = [
            node_id
            for node_id, node in topology.nodes.items()
            if (
                node.kind is NodeKind.REPOSITORY
                and node_id.removeprefix("repo:").lower()
                == claim.repository_id.lower()
            )
        ]
        if len(repository_matches) != 1:
            warning_list.append(
                f"artifact provenance repository match count is "
                f"{len(repository_matches)} for {claim.repository_id}; binding skipped"
            )
            continue

        repository_node_id = repository_matches[0]
        canonical_repository_id = repository_node_id.removeprefix("repo:")
        resolution = revision_resolver.resolve_revision(
            canonical_repository_id, claim.claimed_revision
        )
        if resolution.repository_id.lower() != canonical_repository_id.lower():
            raise ValueError("revision resolver returned a different repository")
        if not resolution.resolved_revision.lower().startswith(
            claim.claimed_revision.lower()
        ):
            raise ValueError(
                "resolved revision does not match claimed immutable revision prefix"
            )
        exact_revision = resolution.resolved_revision.lower()

        receipt = attestation_verifier.verify(
            artifact_reference=claim.artifact_reference,
            artifact_digest=claim.artifact_ref,
            repository_id=canonical_repository_id,
            source_revision=exact_revision,
        )
        if normalize_sha256_digest(receipt.artifact_digest) != claim.artifact_ref:
            raise ValueError("attestation verifier returned a different artifact digest")
        if receipt.repository_id.lower() != canonical_repository_id.lower():
            raise ValueError("attestation verifier returned a different repository")
        if receipt.source_revision.lower() != exact_revision:
            raise ValueError("attestation verifier returned a different source revision")
        if receipt.predicate_type != SLSA_PROVENANCE_V1:
            raise ValueError("attestation verifier returned an unsupported predicate")

        service_node_id = claim.service_id
        instance_node_id = (
            f"service-instance:{claim.service_id.removeprefix('service:')}:"
            f"{claim.service_instance_id}"
        )
        artifact_node_id = claim.artifact_node_id
        source_node_id = f"source:{canonical_repository_id}@{exact_revision}"

        topology.add_node(
            TopologyNode(
                node_id=service_node_id,
                kind=NodeKind.SERVICE,
                label=claim.service_name,
                attributes={"service.namespace": claim.service_namespace},
                evidence=(claim.evidence,),
            )
        )
        topology.add_node(
            TopologyNode(
                node_id=instance_node_id,
                kind=NodeKind.SERVICE_INSTANCE,
                label=claim.service_instance_id,
                attributes={"service.instance.id": claim.service_instance_id},
                evidence=(claim.evidence,),
            )
        )
        topology.add_node(
            TopologyNode(
                node_id=artifact_node_id,
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
        topology.add_node(
            TopologyNode(
                node_id=source_node_id,
                kind=NodeKind.SOURCE_REVISION,
                label=f"{canonical_repository_id}@{exact_revision}",
                attributes={
                    "repository_id": canonical_repository_id,
                    "revision": exact_revision,
                },
                evidence=(claim.evidence,),
            )
        )

        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    instance_node_id,
                    service_node_id,
                    RelationType.INSTANCE_OF,
                    RelationDisposition.OBSERVED,
                ),
                source_id=instance_node_id,
                target_id=service_node_id,
                relation=RelationType.INSTANCE_OF,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(claim.evidence,),
            )
        )
        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    instance_node_id,
                    artifact_node_id,
                    RelationType.RUNS_ARTIFACT,
                    RelationDisposition.OBSERVED,
                    discriminator=(
                        f"{claim.artifact_ref}:{claim.service_version or ''}:"
                        f"{claim.deployment_environment or ''}:"
                        f"{claim.deployment_id or ''}:{claim.deployment_name or ''}"
                    ),
                ),
                source_id=instance_node_id,
                target_id=artifact_node_id,
                relation=RelationType.RUNS_ARTIFACT,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(claim.evidence,),
                attributes={
                    "service.version": claim.service_version,
                    "deployment.environment.name": claim.deployment_environment,
                    "deployment.id": claim.deployment_id,
                    "deployment.name": claim.deployment_name,
                    "claim_ceiling": "RUNTIME_SELF_REPORTED_ARTIFACT",
                },
            )
        )

        attestation_evidence = EvidencePointer(
            source_system=receipt.verifier,
            locator=receipt.verification_ref,
            subject_ref=claim.artifact_ref,
            observed_at=receipt.observed_at,
            evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
            payload_digest=receipt.receipt_digest,
        )
        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    artifact_node_id,
                    source_node_id,
                    RelationType.BUILT_FROM,
                    RelationDisposition.VERIFIED,
                    discriminator=(
                        f"{claim.artifact_ref}:{canonical_repository_id}:"
                        f"{exact_revision}"
                    ),
                ),
                source_id=artifact_node_id,
                target_id=source_node_id,
                relation=RelationType.BUILT_FROM,
                disposition=RelationDisposition.VERIFIED,
                confidence=1.0,
                evidence=(attestation_evidence,),
                verification_ref=(
                    f"artifact-attestation://{claim.artifact_ref}@"
                    f"{canonical_repository_id}@{exact_revision}"
                ),
                attributes={
                    "predicate_type": receipt.predicate_type,
                    "verifier": receipt.verifier,
                    "signer_identity": receipt.signer_identity,
                    "verification_ceiling": (
                        "CRYPTOGRAPHIC_ARTIFACT_BUILD_PROVENANCE"
                    ),
                },
            )
        )

        resolution_evidence = EvidencePointer(
            source_system="github-rest",
            locator=resolution.locator,
            subject_ref=exact_revision,
            observed_at=resolution.observed_at,
            evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
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
                    f"github-commit://{canonical_repository_id}@{exact_revision}"
                ),
                attributes={
                    "verification_ceiling": "SOURCE_REVISION_EXISTS_IN_REPOSITORY"
                },
            )
        )
        verified += 1

    return AttestedArtifactResult(
        claims=claims,
        verified_bindings=verified,
        warnings=tuple(warning_list),
    )


def apply_artifact_deployment_records(
    topology: PortfolioTopology,
    records: tuple[ObservedArtifactDeploymentRecord, ...],
) -> int:
    """Add externally observed artifact deployment records without ID laundering."""

    added = 0
    for record in records:
        normalized = normalize_sha256_digest(record.artifact_digest)
        if normalized is None:
            raise ValueError("deployment record artifact digest must be sha256")
        digest = normalized.split(":", 1)[1]
        artifact_node_id = f"artifact:{normalized}"
        deployment_node_id = (
            f"deployment:{record.source_system}:{record.record_id}"
        )
        evidence = EvidencePointer(
            source_system=record.source_system,
            locator=record.locator,
            subject_ref=record.record_id,
            observed_at=record.observed_at,
            evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
            payload_digest=record.payload_digest,
        )

        topology.add_node(
            TopologyNode(
                node_id=artifact_node_id,
                kind=NodeKind.ARTIFACT,
                label=normalized,
                attributes={
                    "digest_algorithm": "sha256",
                    "digest": digest,
                    "portable_identity": True,
                },
                evidence=(evidence,),
            )
        )
        topology.add_node(
            TopologyNode(
                node_id=deployment_node_id,
                kind=NodeKind.DEPLOYMENT_SURFACE,
                label=record.deployment_name or record.record_id,
                attributes={
                    "record_id": record.record_id,
                    "logical_environment": record.logical_environment,
                    "physical_environment": record.physical_environment,
                    "cluster": record.cluster,
                    "deployment_name": record.deployment_name,
                    "attestation_id": record.attestation_id,
                },
                evidence=(evidence,),
            )
        )
        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    artifact_node_id,
                    deployment_node_id,
                    RelationType.DEPLOYED_TO,
                    RelationDisposition.OBSERVED,
                    discriminator=record.record_id,
                ),
                source_id=artifact_node_id,
                target_id=deployment_node_id,
                relation=RelationType.DEPLOYED_TO,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(evidence,),
                attributes={
                    "claim_ceiling": "EXTERNAL_ARTIFACT_DEPLOYMENT_RECORD",
                    "attestation_id": record.attestation_id,
                },
            )
        )
        added += 1
    return added
