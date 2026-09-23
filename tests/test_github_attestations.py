import unittest

from repairtracker.adapters.github import GitHubReadClient, GitHubReadError


DIGEST = "sha256:" + ("d" * 64)


class AttestationIndexTransport:
    def __init__(self):
        self.calls = []

    def get_json(self, path, query=None):
        self.calls.append((path, query))
        if path == f"/repos/acme/app/attestations/{DIGEST}":
            return {
                "attestations": [
                    {
                        "repository_id": 123,
                        "bundle_url": "https://example.test/bundle.json",
                        "initiator": "user",
                    }
                ]
            }
        raise AssertionError(f"unexpected GET: {path} {query}")


class NotFoundTransport:
    def get_json(self, path, query=None):
        raise GitHubReadError("not found", status_code=404)


class GitHubAttestationIndexTests(unittest.TestCase):
    def test_listing_is_explicitly_reference_only(self):
        transport = AttestationIndexTransport()
        result = GitHubReadClient(transport=transport).list_attestations(
            "acme/app", DIGEST
        )
        self.assertEqual(len(result.references), 1)
        reference = result.references[0]
        self.assertEqual(reference.subject_digest, DIGEST)
        self.assertEqual(reference.repository_id, "acme/app")
        self.assertEqual(reference.initiator, "user")
        self.assertEqual(
            transport.calls[0][1]["predicate_type"],
            "provenance",
        )

    def test_not_found_is_preserved_as_ambiguous_incomplete_result(self):
        result = GitHubReadClient(
            transport=NotFoundTransport()
        ).list_attestations("acme/app", DIGEST)
        self.assertEqual(result.references, ())
        self.assertTrue(any("completeness is unknown" in w for w in result.warnings))

    def test_non_sha256_subject_is_rejected_before_transport(self):
        transport = AttestationIndexTransport()
        client = GitHubReadClient(transport=transport)
        with self.assertRaises(ValueError):
            client.list_attestations("acme/app", "sha1:" + ("a" * 40))
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
