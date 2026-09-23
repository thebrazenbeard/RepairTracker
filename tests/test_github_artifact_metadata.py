import unittest

from repairtracker.adapters.github import GitHubReadClient, GitHubReadError


DIGEST = "sha256:" + ("a" * 64)


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
                            "sha256:" + ("b" * 64)
                            if self.wrong_digest
                            else DIGEST
                        ),
                        "logical_environment": "production",
                        "physical_environment": "us-east",
                        "cluster": "cluster-1",
                        "deployment_name": "api-prod",
                        "attestation_id": 456,
                        "created": "2026-09-23T12:00:00Z",
                        "updated_at": "2026-09-23T12:05:00Z",
                    }
                ],
            }
        raise AssertionError(f"unexpected GET: {path} {query}")


class GitHubArtifactMetadataTests(unittest.TestCase):
    def test_deployment_records_are_bound_to_requested_artifact_digest(self):
        transport = DeploymentTransport()
        records = GitHubReadClient(
            transport=transport
        ).observe_artifact_deployments("acme", DIGEST)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.artifact_digest, DIGEST)
        self.assertEqual(record.logical_environment, "production")
        self.assertEqual(record.attestation_id, "456")
        self.assertTrue(record.payload_digest)
        self.assertIn(DIGEST, transport.calls[0][0])

    def test_mismatched_deployment_record_digest_fails_closed(self):
        with self.assertRaises(GitHubReadError):
            GitHubReadClient(
                transport=DeploymentTransport(wrong_digest=True)
            ).observe_artifact_deployments("acme", DIGEST)


if __name__ == "__main__":
    unittest.main()
