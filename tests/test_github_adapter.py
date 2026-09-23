import base64
import unittest

from repairtracker.adapters.github import GitHubReadClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def get_json(self, path, query=None):
        self.calls.append((path, query))
        if path == "/repos/acme/app":
            return {"default_branch": "main"}
        if path == "/repos/acme/app/branches/main":
            return {"commit": {"sha": "a" * 40}}
        if path == f"/repos/acme/app/git/trees/{'a' * 40}":
            return {
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": "package.json", "size": 80},
                    {"type": "blob", "path": ".github/workflows/ci.yml", "size": 20},
                    {"type": "blob", "path": "tests/test_a.py", "size": 20},
                ],
            }
        if path == "/repos/acme/app/contents/package.json":
            return {
                "encoding": "base64",
                "size": 50,
                "content": base64.b64encode(
                    b'{"name":"app","dependencies":{"lib":"1"}}'
                ).decode("ascii"),
            }
        raise AssertionError(f"unexpected GET: {path} {query}")


class GitHubAdapterTests(unittest.TestCase):
    def test_read_client_binds_exact_default_branch_revision(self):
        transport = FakeTransport()
        observation = GitHubReadClient(transport=transport).observe_repository(
            "acme/app"
        )
        self.assertEqual(observation.repository_id, "acme/app")
        self.assertEqual(observation.revision, "a" * 40)
        self.assertEqual(observation.default_branch, "main")
        self.assertIn("package.json", observation.files)
        self.assertEqual(len(observation.workflows), 1)
        self.assertTrue(
            all(path.startswith("/repos/") for path, _ in transport.calls)
        )

    def test_invalid_repo_name_fails_before_transport(self):
        transport = FakeTransport()
        client = GitHubReadClient(transport=transport)
        with self.assertRaises(ValueError):
            client.observe_repository("https://example.com/not-allowed")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
