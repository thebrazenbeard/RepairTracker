from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .model import EvidenceClass, canonical_digest


class NodeKind(StrEnum):
    PORTFOLIO = "PORTFOLIO"
    REPOSITORY = "REPOSITORY"
    PACKAGE = "PACKAGE"
    SERVICE = "SERVICE"
    WORKFLOW = "WORKFLOW"
    TEST_SURFACE = "TEST_SURFACE"
    BUILD_SURFACE = "BUILD_SURFACE"
    DEPLOYMENT_SURFACE = "DEPLOYMENT_SURFACE"
    DATASTORE = "DATASTORE"
    CAPABILITY_PROVIDER = "CAPABILITY_PROVIDER"


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    PROVIDES = "PROVIDES"
    DECLARES_DEPENDENCY = "DECLARES_DEPENDENCY"
    DEPENDS_ON = "DEPENDS_ON"
    CALLS = "CALLS"
    TESTS = "TESTS"
    BUILDS = "BUILDS"
    DEPLOYS = "DEPLOYS"
    EMITS_TELEMETRY_TO = "EMITS_TELEMETRY_TO"
    PROVIDES_CAPABILITY = "PROVIDES_CAPABILITY"
    REFERENCES = "REFERENCES"


class RelationDisposition(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    VERIFIED = "VERIFIED"


class CurrentnessKind(StrEnum):
    EXACT_REVISION = "EXACT_REVISION"
    OBSERVED_UNPINNED = "OBSERVED_UNPINNED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    source_system: str
    locator: str
    subject_ref: str | None
    observed_at: str
    evidence_class: EvidenceClass
    payload_digest: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentnessEvidence:
    source_system: str
    subject_id: str
    observed_at: str
    kind: CurrentnessKind
    revision: str | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        if self.kind is CurrentnessKind.EXACT_REVISION and not self.revision:
            raise ValueError("EXACT_REVISION currentness requires a revision")


@dataclass(frozen=True, slots=True)
class TopologyNode:
    node_id: str
    kind: NodeKind
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidencePointer, ...] = ()


@dataclass(frozen=True, slots=True)
class TopologyEdge:
    edge_id: str
    source_id: str
    target_id: str
    relation: RelationType
    disposition: RelationDisposition
    confidence: float | None
    evidence: tuple[EvidencePointer, ...] = ()
    inference_rule: str | None = None
    verification_ref: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("edge confidence must be between 0 and 1")
        if (
            self.disposition in {
                RelationDisposition.OBSERVED,
                RelationDisposition.VERIFIED,
            }
            and self.confidence is None
        ):
            raise ValueError("observed/verified topology edges require confidence")
        if self.disposition is RelationDisposition.INFERRED and not self.inference_rule:
            raise ValueError("inferred topology edges require an inference_rule")
        if self.disposition in {
            RelationDisposition.OBSERVED,
            RelationDisposition.VERIFIED,
        } and not self.evidence:
            raise ValueError(f"{self.disposition} topology edges require evidence")
        if (
            self.disposition is RelationDisposition.VERIFIED
            and not self.verification_ref
        ):
            raise ValueError("verified topology edges require verification_ref")
        if (
            self.disposition is not RelationDisposition.VERIFIED
            and self.verification_ref is not None
        ):
            raise ValueError(
                "verification_ref is reserved for VERIFIED topology edges"
            )


def topology_edge_id(
    source_id: str,
    target_id: str,
    relation: RelationType,
    disposition: RelationDisposition,
    discriminator: str = "",
) -> str:
    return canonical_digest(
        {
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation.value,
            "disposition": disposition.value,
            "discriminator": discriminator,
        }
    )[:24]


@dataclass(slots=True)
class PortfolioTopology:
    portfolio_id: str
    nodes: dict[str, TopologyNode] = field(default_factory=dict)
    edges: dict[str, TopologyEdge] = field(default_factory=dict)
    currentness: dict[str, CurrentnessEvidence] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: TopologyNode) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
            return
        if (
            existing.kind != node.kind
            or existing.label != node.label
            or existing.attributes != node.attributes
        ):
            raise ValueError(f"topology node collision: {node.node_id}")
        merged_evidence = tuple(
            dict.fromkeys((*existing.evidence, *node.evidence))
        )
        self.nodes[node.node_id] = TopologyNode(
            node_id=existing.node_id,
            kind=existing.kind,
            label=existing.label,
            attributes=existing.attributes,
            evidence=merged_evidence,
        )

    def add_edge(self, edge: TopologyEdge) -> None:
        if edge.source_id not in self.nodes:
            raise ValueError(f"unknown topology source node: {edge.source_id}")
        if edge.target_id not in self.nodes:
            raise ValueError(f"unknown topology target node: {edge.target_id}")
        existing = self.edges.get(edge.edge_id)
        if existing is not None and existing != edge:
            raise ValueError(f"topology edge collision: {edge.edge_id}")
        self.edges[edge.edge_id] = edge

    def bind_currentness(self, evidence: CurrentnessEvidence) -> None:
        existing = self.currentness.get(evidence.subject_id)
        if existing is not None and existing != evidence:
            raise ValueError(f"currentness already bound for {evidence.subject_id}")
        self.currentness[evidence.subject_id] = evidence

    @property
    def currentness_digest(self) -> str:
        rows = [
            {
                "subject_id": subject_id,
                "kind": item.kind.value,
                "revision": item.revision,
            }
            for subject_id, item in sorted(self.currentness.items())
        ]
        return canonical_digest(rows)

    @property
    def digest(self) -> str:
        nodes = []
        for node_id, node in sorted(self.nodes.items()):
            row = asdict(node)
            row["kind"] = node.kind.value
            row["evidence"] = [
                {**asdict(item), "evidence_class": item.evidence_class.value}
                for item in node.evidence
            ]
            nodes.append((node_id, row))

        edges = []
        for edge_id, edge in sorted(self.edges.items()):
            row = asdict(edge)
            row["relation"] = edge.relation.value
            row["disposition"] = edge.disposition.value
            row["evidence"] = [
                {**asdict(item), "evidence_class": item.evidence_class.value}
                for item in edge.evidence
            ]
            edges.append((edge_id, row))

        return canonical_digest(
            {
                "portfolio_id": self.portfolio_id,
                "nodes": nodes,
                "edges": edges,
                "currentness_digest": self.currentness_digest,
                "warnings": sorted(self.warnings),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "REPAIRTRACKER_PORTFOLIO_TOPOLOGY_V0",
            "portfolio_id": self.portfolio_id,
            "nodes": [
                {
                    **asdict(node),
                    "kind": node.kind.value,
                    "evidence": [
                        {**asdict(item), "evidence_class": item.evidence_class.value}
                        for item in node.evidence
                    ],
                }
                for _, node in sorted(self.nodes.items())
            ],
            "edges": [
                {
                    **asdict(edge),
                    "relation": edge.relation.value,
                    "disposition": edge.disposition.value,
                    "evidence": [
                        {**asdict(item), "evidence_class": item.evidence_class.value}
                        for item in edge.evidence
                    ],
                }
                for _, edge in sorted(self.edges.items())
            ],
            "currentness": [
                {**asdict(item), "kind": item.kind.value}
                for _, item in sorted(self.currentness.items())
            ],
            "currentness_digest": self.currentness_digest,
            "warnings": sorted(self.warnings),
            "digest": self.digest,
        }
