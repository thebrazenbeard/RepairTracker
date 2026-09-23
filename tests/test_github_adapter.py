import base64
import unittest

from repairtracker.adapters.github import GitHubReadClient, GitHubReadError


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


class MovingTransport:
    def __init__(self):
        self.branch_reads = 0

    def get_json(self, path, query=None):
        if path == "/repos/acme/app":
            return {"default_branch": "main"}
        if path == "/repos/acme/app/branches/main":
            self.branch_reads += 1
            char = ["a", "b", "c", "d"][self.branch_reads - 1]
            return {"commit": {"sha": char * 40}}
        if "/git/trees/" in path:
            return {"truncated": False, "tree": []}
        raise AssertionError(f"unexpected GET: {path} {query}")


class OwnerTransport:
    def __init__(self):
        self.calls = []

    def get_json(self, path, query=None):
        self.calls.append((path, query))
        if path == "/users/acme/repos":
            return [
                {"full_name": "acme/a", "archived": False, "fork": False},
                {"full_name": "acme/archive", "archived": True, "fork": False},
                {"full_name": "acme/fork", "archived": False, "fork": True},
            ]
        raise AssertionError(f"unexpected GET: {path} {query}")


class AuthenticatedTransport:
    def __init__(self):
        self.calls = []

    def get_json(self, path, query=None):
        self.calls.append((path, query))
        if path == "/user/repos":
            return [
                {"full_name": "acme/private", "archived": False, "fork": False},
                {"full_name": "acme/fork", "archived": False, "fork": True},
            ]
        raise AssertionError(f"unexpected GET: {path} {query}")


class RevisionTransport:
    def get_json(self, path, query=None):
        if path == "/repos/acme/app/commits/abcdef1":
            return {"sha": "abcdef1" + ("a" * 33)}
        raise AssertionError(f"unexpected GET: {path} {query}")


class GitHubAdapterTests(unittest.TestCase):
    def test_read_client_binds_stable_exact_default_branch_revision(self):
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

    def test_unstable_default_branch_fails_closed_after_retry(self):
        client = GitHubReadClient(transport=MovingTransport())
        with self.assertRaises(GitHubReadError):
            client.observe_repository("acme/app")

    def test_owner_discovery_is_bounded_and_filters_archived_forks(self):
        transport = OwnerTransport()
        result = GitHubReadClient(transport=transport).list_owner_repositories(
            "acme",
            owner_kind="user",
            max_repositories=10,
        )
        self.assertEqual(result.repositories, ("acme/a",))
        self.assertEqual(result.warnings, ())
        self.assertEqual(transport.calls[0][0], "/users/acme/repos")
        self.assertEqual(transport.calls[0][1]["per_page"], "100")

    def test_authenticated_discovery_uses_user_repositories_endpoint(self):
        transport = AuthenticatedTransport()
        result = GitHubReadClient(
            transport=transport
        ).list_authenticated_repositories(max_repositories=10)
        self.assertEqual(result.repositories, ("acme/private",))
        self.assertEqual(transport.calls[0][0], "/user/repos")
        self.assertEqual(transport.calls[0][1]["visibility"], "all")
        self.assertIn("owner", transport.calls[0][1]["affiliation"])

    def test_revision_resolution_returns_exact_repository_commit(self):
        result = GitHubReadClient(
            transport=RevisionTransport()
        ).resolve_revision("acme/app", "abcdef1")
        self.assertEqual(result.repository_id, "acme/app")
        self.assertEqual(result.requested_revision, "abcdef1")
        self.assertEqual(result.resolved_revision, "abcdef1" + ("a" * 33))

    def test_symbolic_revision_is_rejected_before_transport(self):
        transport = RevisionTransport()
        with self.assertRaises(ValueError):
            GitHubReadClient(transport=transport).resolve_revision(
                "acme/app", "main"
            )

    def test_invalid_repo_name_fails_before_transport(self):
        transport = FakeTransport()
        client = GitHubReadClient(transport=transport)
        with self.assertRaises(ValueError):
            client.observe_repository("https://example.com/not-allowed")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
