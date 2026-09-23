from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .artifact import RuntimeArtifactClaim
from .model import EvidenceClass, canonical_digest
from .runtime_binding import RevisionResolver
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


IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"
SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
_REPOSITORY_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_REVISION = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


@dataclass(frozen=True, slots=True)
class AttestationVerificationReceipt:
    verifier: str
    verified_at: str
    repository_id: str
    subject_algorithm: str
    subject_digest: str
    predicate_type: str
    source_repository_id: str
    source_revision: str
    statement: dict[str, Any]
    verification_locator: str
    signer_policy: str | None = None
    witness_timestamps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.verifier.strip():
            raise ValueError("attestation verifier is required")
        if not _REPOSITORY_ID.fullmatch(self.repository_id):
            raise ValueError("invalid attestation repository_id")
        if not _REPOSITORY_ID.fullmatch(self.source_repository_id):
            raise ValueError("invalid attestation source_repository_id")
        if self.subject_algorithm != "sha256":
            raise ValueError("V0 attestation binding supports sha256 subjects only")
        if not _SHA256.fullmatch(self.subject_digest):
            raise ValueError("invalid sha256 attestation subject digest")
        if self.predicate_type != SLSA_PROVENANCE_V1:
            raise ValueError("V0 requires SLSA provenance v1")
        if not _GIT_REVISION.fullmatch(self.source_revision):
            raise ValueError(
                "verified source revision must be a full 40/64 hex Git revision"
            )
        if not isinstance(self.statement, dict):
            raise ValueError("verified attestation statement must be an object")

    @property
    def statement_digest(self) -> str:
        return canonical_digest(self.statement)


@dataclass(frozen=True, slots=True)
class SLSAProvenanceClaim:
    subject_algorithm: str
    subject_digest: str
    source_repository_id: str
    source_revision: str
    build_type: str | None
    builder_id: str | None
    invocation_id: str | None
    statement_digest: str


@dataclass(frozen=True, slots=True)
class ArtifactProvenanceBindingResult:
    provenance: SLSAProvenanceClaim
    artifact_node_id: str
    source_node_id: str
    repository_node_id: str
    verification_ref: str


def _github_repository_from_git_uri(uri: str) -> str | None:
    if not uri.startswith("git+https://"):
        return None
    parsed = urlparse(uri[4:])
    if (parsed.hostname or "").lower() != "github.com":
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None or parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment or parsed.params:
        return None

    path = parsed.path.strip("/")
    repository_path = path.split("@", 1)[0]
    if repository_path.endswith(".git"):
        repository_path = repository_path[:-4]
    parts = repository_path.split("/")
    if len(parts) != 2:
        return None
    repository_id = f"{parts[0]}/{parts[1]}"
    return repository_id if _REPOSITORY_ID.fullmatch(repository_id) else None


def _git_revision_from_digest_set(digest: Any) -> str | None:
    if not isinstance(digest, Mapping):
        return None
    value = digest.get("gitCommit")
    if isinstance(value, str) and _GIT_REVISION.fullmatch(value):
        return value.lower()

    sha1 = digest.get("sha1")
    if isinstance(sha1, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha1):
        return sha1.lower()

    sha256 = digest.get("sha256")
    if isinstance(sha256, str) and _SHA256.fullmatch(sha256):
        return sha256.lower()
    return None


def parse_verified_slsa_provenance(
    receipt: AttestationVerificationReceipt,
) -> SLSAProvenanceClaim:
    statement = receipt.statement
    if statement.get("_type") != IN_TOTO_STATEMENT_V1:
        raise ValueError("attestation is not an in-toto Statement v1")
    if statement.get("predicateType") != receipt.predicate_type:
        raise ValueError("attestation predicate type does not match verification receipt")

    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        raise ValueError("attestation subject must be a list")
    subject_matches = []
    for subject in subjects:
        if not isinstance(subject, Mapping):
            continue
        digest = subject.get("digest")
        if not isinstance(digest, Mapping):
            continue
        value = digest.get(receipt.subject_algorithm)
        if (
            isinstance(value, str)
            and value.lower() == receipt.subject_digest.lower()
        ):
            subject_matches.append(subject)
    if not subject_matches:
        raise ValueError("verified subject digest is absent from attestation statement")

    predicate = statement.get("predicate")
    if not isinstance(predicate, Mapping):
        raise ValueError("SLSA provenance predicate must be an object")
    build_definition = predicate.get("buildDefinition")
    if not isinstance(build_definition, Mapping):
        raise ValueError("SLSA provenance buildDefinition is required")

    resolved = build_definition.get("resolvedDependencies", [])
    if not isinstance(resolved, list):
        raise ValueError("resolvedDependencies must be a list")

    source_candidates: set[tuple[str, str]] = set()
    for dependency in resolved:
        if not isinstance(dependency, Mapping):
            continue
        uri = dependency.get("uri")
        if not isinstance(uri, str):
            continue
        repository_id = _github_repository_from_git_uri(uri)
        revision = _git_revision_from_digest_set(dependency.get("digest"))
        if repository_id is not None and revision is not None:
            source_candidates.add((repository_id, revision))

    matching = {
        (repository_id, revision)
        for repository_id, revision in source_candidates
        if repository_id.lower() == receipt.source_repository_id.lower()
        and revision.lower() == receipt.source_revision.lower()
    }
    if len(matching) != 1:
        raise ValueError(
            "SLSA provenance does not contain exactly one dependency matching "
            "the cryptographically verified source repository/revision"
        )
    source_repository_id, source_revision = next(iter(matching))

    external_parameters = build_definition.get("externalParameters")
    if isinstance(external_parameters, Mapping):
        workflow = external_parameters.get("workflow")
        if isinstance(workflow, Mapping):
            repository = workflow.get("repository")
            if isinstance(repository, str):
                parsed = urlparse(repository)
                path = parsed.path.strip("/")
                if path.endswith(".git"):
                    path = path[:-4]
                canonical = (
                    parsed.scheme.lower() == "https"
                    and (parsed.hostname or "").lower() == "github.com"
                    and parsed.port is None
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.query
                    and not parsed.fragment
                    and not parsed.params
                    and _REPOSITORY_ID.fullmatch(path)
                )
                if not canonical:
                    raise ValueError(
                        "workflow repository metadata is not a canonical GitHub "
                        "repository URL"
                    )
                if path.lower() != source_repository_id.lower():
                    raise ValueError(
                        "workflow repository disagrees with verified source "
                        "repository"
                    )

    run_details = predicate.get("runDetails")
    builder_id = None
    invocation_id = None
    if isinstance(run_details, Mapping):
        builder = run_details.get("builder")
        if isinstance(builder, Mapping) and isinstance(builder.get("id"), str):
            builder_id = builder["id"]
        metadata = run_details.get("metadata")
        if isinstance(metadata, Mapping) and isinstance(
            metadata.get("invocationId"), str
        ):
            invocation_id = metadata["invocationId"]

    build_type = build_definition.get("buildType")
    if not isinstance(build_type, str):
        build_type = None

    return SLSAProvenanceClaim(
        subject_algorithm=receipt.subject_algorithm,
        subject_digest=receipt.subject_digest.lower(),
        source_repository_id=source_repository_id,
        source_revision=source_revision.lower(),
        build_type=build_type,
        builder_id=builder_id,
        invocation_id=invocation_id,
        statement_digest=receipt.statement_digest,
    )


def bind_verified_artifact_provenance(
    topology: PortfolioTopology,
    artifact: RuntimeArtifactClaim,
    receipt: AttestationVerificationReceipt,
    resolver: RevisionResolver,
) -> ArtifactProvenanceBindingResult:
    if artifact.digest_algorithm != receipt.subject_algorithm:
        raise ValueError("runtime artifact algorithm does not match attestation")
    if artifact.digest.lower() != receipt.subject_digest.lower():
        raise ValueError("runtime artifact digest does not match attestation subject")
    if artifact.artifact_node_id not in topology.nodes:
        raise ValueError(
            "runtime artifact must be observed in topology before provenance binding"
        )

    provenance = parse_verified_slsa_provenance(receipt)

    repository_matches = [
        node_id
        for node_id, node in topology.nodes.items()
        if (
            node.kind is NodeKind.REPOSITORY
            and node_id.removeprefix("repo:").lower()
            == provenance.source_repository_id.lower()
        )
    ]
    if len(repository_matches) != 1:
        raise ValueError(
            "verified provenance source repository is not uniquely present "
            "in the observed portfolio"
        )
    repository_node_id = repository_matches[0]
    canonical_repository_id = repository_node_id.removeprefix("repo:")

    resolution = resolver.resolve_revision(
        canonical_repository_id, provenance.source_revision
    )
    if resolution.repository_id.lower() != canonical_repository_id.lower():
        raise ValueError("revision resolver returned a different repository")
    if resolution.resolved_revision.lower() != provenance.source_revision.lower():
        raise ValueError(
            "attested source revision does not resolve to the same exact commit"
        )

    source_node_id = (
        f"source:{canonical_repository_id}@{provenance.source_revision.lower()}"
    )
    verification_ref = f"attestation://{receipt.statement_digest}"

    attestation_evidence = EvidencePointer(
        source_system=receipt.verifier,
        locator=receipt.verification_locator,
        subject_ref=artifact.artifact_ref,
        observed_at=receipt.verified_at,
        evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
        payload_digest=canonical_digest(
            {
                "statement_digest": receipt.statement_digest,
                "subject": artifact.artifact_ref,
                "source_repository_id": receipt.source_repository_id,
                "source_revision": receipt.source_revision.lower(),
                "predicate_type": receipt.predicate_type,
                "signer_policy": receipt.signer_policy,
                "witness_timestamps": list(receipt.witness_timestamps),
            }
        ),
    )
    topology.add_node(
        TopologyNode(
            node_id=source_node_id,
            kind=NodeKind.SOURCE_REVISION,
            label=f"{canonical_repository_id}@{provenance.source_revision.lower()}",
            attributes={
                "repository_id": canonical_repository_id,
                "revision": provenance.source_revision.lower(),
            },
            evidence=(attestation_evidence,),
        )
    )
    topology.add_edge(
        TopologyEdge(
            edge_id=topology_edge_id(
                artifact.artifact_node_id,
                source_node_id,
                RelationType.BUILT_FROM,
                RelationDisposition.VERIFIED,
                discriminator=receipt.statement_digest,
            ),
            source_id=artifact.artifact_node_id,
            target_id=source_node_id,
            relation=RelationType.BUILT_FROM,
            disposition=RelationDisposition.VERIFIED,
            confidence=1.0,
            evidence=(attestation_evidence,),
            verification_ref=verification_ref,
            attributes={
                "predicate_type": receipt.predicate_type,
                "build_type": provenance.build_type,
                "builder_id": provenance.builder_id,
                "invocation_id": provenance.invocation_id,
                "verification_ceiling": (
                    "CRYPTO_VERIFIED_ATTESTATION_SOURCE_BINDING"
                ),
                "signer_workflow_enforced": receipt.signer_policy is not None,
                "build_platform_integrity": "NOT_ESTABLISHED",
                "predicate_trust_ceiling": (
                    "SIGNED_BUT_WORKFLOW_CONTEXT_CAN_INFLUENCE_PREDICATE"
                ),
            },
        )
    )

    resolution_evidence = EvidencePointer(
        source_system="github-rest",
        locator=resolution.locator,
        subject_ref=provenance.source_revision.lower(),
        observed_at=resolution.observed_at,
        evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
        payload_digest=canonical_digest(
            {
                "repository_id": resolution.repository_id,
                "requested_revision": resolution.requested_revision,
                "resolved_revision": resolution.resolved_revision.lower(),
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
                discriminator=provenance.source_revision.lower(),
            ),
            source_id=source_node_id,
            target_id=repository_node_id,
            relation=RelationType.BELONGS_TO,
            disposition=RelationDisposition.VERIFIED,
            confidence=1.0,
            evidence=(resolution_evidence,),
            verification_ref=(
                f"github-commit://{canonical_repository_id}@"
                f"{provenance.source_revision.lower()}"
            ),
            attributes={
                "verification_ceiling": "SOURCE_REVISION_EXISTS_IN_REPOSITORY"
            },
        )
    )

    return ArtifactProvenanceBindingResult(
        provenance=provenance,
        artifact_node_id=artifact.artifact_node_id,
        source_node_id=source_node_id,
        repository_node_id=repository_node_id,
        verification_ref=verification_ref,
    )
