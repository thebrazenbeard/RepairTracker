from __future__ import annotations

from dataclasses import dataclass

from .model import EvidenceClass
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

    def __post_init__(self) -> None:
        if not self.source_system.strip():
            raise ValueError("deployment record source_system is required")
        if not self.record_id.strip():
            raise ValueError("deployment record_id is required")
        if (
            not self.artifact_digest.startswith("sha256:")
            or len(self.artifact_digest) != 71
            or any(
                ch not in "0123456789abcdef"
                for ch in self.artifact_digest.removeprefix("sha256:").lower()
            )
        ):
            raise ValueError("deployment artifact_digest must be sha256:HEX")
        if not self.payload_digest.strip():
            raise ValueError("deployment payload_digest is required")


def apply_artifact_deployment_records(
    topology: PortfolioTopology,
    records: tuple[ObservedArtifactDeploymentRecord, ...],
) -> int:
    """Add external artifact deployment records without promoting them to proof.

    A deployment record says an external system recorded artifact D at a
    deployment surface. It does not prove runtime admission, runtime presence,
    or cryptographic build provenance.
    """

    added = 0
    for record in records:
        digest = record.artifact_digest.lower()
        digest_hex = digest.removeprefix("sha256:")
        artifact_node_id = f"artifact:{digest}"
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
                label=digest,
                attributes={
                    "digest_algorithm": "sha256",
                    "digest": digest_hex,
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
