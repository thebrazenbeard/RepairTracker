import unittest

from repairtracker.model import EvidenceClass
from repairtracker.topology import (
    EvidencePointer,
    NodeKind,
    PortfolioTopology,
    RelationDisposition,
    RelationType,
    TopologyEdge,
    TopologyNode,
    topology_edge_id,
)


class TopologyReplayTests(unittest.TestCase):
    def test_repeated_semantic_edge_merges_new_evidence(self):
        topology = PortfolioTopology("test")
        topology.add_node(TopologyNode("a", NodeKind.SERVICE, "a"))
        topology.add_node(TopologyNode("b", NodeKind.SERVICE, "b"))

        first_evidence = EvidencePointer(
            source_system="otel",
            locator="otel://one",
            subject_ref="trace:one",
            observed_at="2026-09-23T12:00:00+00:00",
            evidence_class=EvidenceClass.OBSERVED,
        )
        second_evidence = EvidencePointer(
            source_system="otel",
            locator="otel://two",
            subject_ref="trace:two",
            observed_at="2026-09-23T12:01:00+00:00",
            evidence_class=EvidenceClass.OBSERVED,
        )
        edge_id = topology_edge_id(
            "a", "b", RelationType.CALLS, RelationDisposition.OBSERVED, "same"
        )
        common = dict(
            edge_id=edge_id,
            source_id="a",
            target_id="b",
            relation=RelationType.CALLS,
            disposition=RelationDisposition.OBSERVED,
            confidence=1.0,
            attributes={"semantic": "same"},
        )
        topology.add_edge(
            TopologyEdge(evidence=(first_evidence,), **common)
        )
        topology.add_edge(
            TopologyEdge(evidence=(second_evidence,), **common)
        )
        self.assertEqual(len(topology.edges[edge_id].evidence), 2)

    def test_repeated_edge_with_changed_semantics_still_collides(self):
        topology = PortfolioTopology("test")
        topology.add_node(TopologyNode("a", NodeKind.SERVICE, "a"))
        topology.add_node(TopologyNode("b", NodeKind.SERVICE, "b"))
        evidence = EvidencePointer(
            source_system="test",
            locator="test://one",
            subject_ref="one",
            observed_at="2026-09-23T12:00:00+00:00",
            evidence_class=EvidenceClass.OBSERVED,
        )
        edge_id = topology_edge_id(
            "a", "b", RelationType.CALLS, RelationDisposition.OBSERVED, "same"
        )
        topology.add_edge(
            TopologyEdge(
                edge_id=edge_id,
                source_id="a",
                target_id="b",
                relation=RelationType.CALLS,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(evidence,),
                attributes={"semantic": "one"},
            )
        )
        with self.assertRaises(ValueError):
            topology.add_edge(
                TopologyEdge(
                    edge_id=edge_id,
                    source_id="a",
                    target_id="b",
                    relation=RelationType.CALLS,
                    disposition=RelationDisposition.OBSERVED,
                    confidence=1.0,
                    evidence=(evidence,),
                    attributes={"semantic": "changed"},
                )
            )


if __name__ == "__main__":
    unittest.main()
