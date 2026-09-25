import unittest

from repairtracker.adapters.github import GitHubReadClient, GitHubReadError
from repairtracker.deployment import apply_artifact_deployment_records
from repairtracker.topology import (
    PortfolioTopology,
    RelationDisposition,
    RelationType,
)


DIGEST = "sha256:" + ("d" * 64)


class DeploymentTransport:
    def __init__(self, *, wrong_digest=False):
        self.calls = []
        self.wrong_digest = wrong_digest

    def get_json(self, path, query=None):
        self.calls.append((path, query))
        if "/metadata/deployment-records" in path:
            return {
                "total_count": 1,
                "deployment_records": [
                    {
                        "id": 123,
                        "digest": (
                            "sha256:" + ("e" * 64)
                            if self.wrong_digest
                            else DIGEST
                        ),
                        "logical_environment": "prod",
                        "physical_environment": "pacific-east",
                        "cluster": "moda-1",
                        "deployment_name": "prod-deployment",
                        "created": "2011-01-26T19:14:43Z",
                        "updated_at": "2011-01-26T19:14:43Z",
                        "attestation_id": 456,
                    }
                ],
            }
        raise AssertionError(f"unexpected GET: {path} {query}")


class ArtifactDeploymentTests(unittest.TestCase):
    def test_github_deployment_record_maps_exact_documented_fields(self):
        transport = DeploymentTransport()
        records = GitHubReadClient(
            transport=transport
        ).observe_artifact_deployments("acme", DIGEST)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.artifact_digest, DIGEST)
        self.assertEqual(record.logical_environment, "prod")
        self.assertEqual(record.physical_environment, "pacific-east")
        self.assertEqual(record.cluster, "moda-1")
        self.assertEqual(record.deployment_name, "prod-deployment")
        self.assertEqual(record.attestation_id, "456")
        self.assertTrue(record.payload_digest)

        topology = PortfolioTopology("test")
        self.assertEqual(apply_artifact_deployment_records(topology, records), 1)
        edges = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.DEPLOYED_TO
        ]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].disposition, RelationDisposition.OBSERVED)
        self.assertEqual(
            edges[0].attributes["claim_ceiling"],
            "EXTERNAL_ARTIFACT_DEPLOYMENT_RECORD",
        )

    def test_wrong_digest_fails_closed(self):
        with self.assertRaises(GitHubReadError):
            GitHubReadClient(
                transport=DeploymentTransport(wrong_digest=True)
            ).observe_artifact_deployments("acme", DIGEST)

    def test_deployment_record_is_not_attestation_verification(self):
        records = GitHubReadClient(
            transport=DeploymentTransport()
        ).observe_artifact_deployments("acme", DIGEST)
        topology = PortfolioTopology("test")
        apply_artifact_deployment_records(topology, records)
        self.assertFalse(
            any(
                edge.relation is RelationType.BUILT_FROM
                for edge in topology.edges.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
