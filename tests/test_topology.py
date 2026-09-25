import unittest

from repairtracker.model import EvidenceClass
from repairtracker.topology import (
    EvidencePointer,
    RelationDisposition,
    RelationType,
    TopologyEdge,
)


class TopologyTests(unittest.TestCase):
    def test_verified_relation_requires_explicit_verification_reference(self):
        evidence = EvidencePointer(
            source_system="test",
            locator="test://evidence",
            subject_ref="subject",
            observed_at="2026-09-23T11:00:00+00:00",
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest="digest",
        )
        with self.assertRaises(ValueError):
            TopologyEdge(
                edge_id="edge",
                source_id="a",
                target_id="b",
                relation=RelationType.DEPENDS_ON,
                disposition=RelationDisposition.VERIFIED,
                confidence=1.0,
                evidence=(evidence,),
            )

        edge = TopologyEdge(
            edge_id="edge",
            source_id="a",
            target_id="b",
            relation=RelationType.DEPENDS_ON,
            disposition=RelationDisposition.VERIFIED,
            confidence=1.0,
            evidence=(evidence,),
            verification_ref="verification://exact-subject-receipt",
        )
        self.assertEqual(
            edge.verification_ref,
            "verification://exact-subject-receipt",
        )


if __name__ == "__main__":
    unittest.main()
