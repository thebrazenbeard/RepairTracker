import tempfile
import unittest
from pathlib import Path

from repairtracker.portfolio import (
    RepositoryObservation,
    bootstrap_portfolio,
    observe_local_repository,
)
from repairtracker.topology import (
    CurrentnessKind,
    RelationDisposition,
    RelationType,
)


def observation(repo, sha, files, paths=()):
    return RepositoryObservation(
        repository_id=repo,
        default_branch="main",
        revision=sha,
        observed_at="2026-09-23T10:00:00+00:00",
        source_system="fixture",
        source_locator=f"fixture://{repo}/{sha}",
        files=files,
        tree_paths=tuple(paths or files.keys()),
    )


class PortfolioTests(unittest.TestCase):
    def test_cross_repo_dependency_is_inferred_not_promoted_to_observed(self):
        app = observation(
            "acme/app",
            "a" * 40,
            {
                "package.json": (
                    '{"name":"@acme/app","dependencies":{"@acme/lib":"1.0.0"}}'
                )
            },
        )
        lib = observation(
            "acme/lib",
            "b" * 40,
            {"package.json": '{"name":"@acme/lib","version":"1.0.0"}'},
        )

        topology = bootstrap_portfolio([app, lib], portfolio_id="acme")
        dependency_edges = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.DEPENDS_ON
        ]
        self.assertEqual(len(dependency_edges), 1)
        edge = dependency_edges[0]
        self.assertEqual(edge.source_id, "repo:acme/app")
        self.assertEqual(edge.target_id, "repo:acme/lib")
        self.assertEqual(edge.disposition, RelationDisposition.INFERRED)
        self.assertEqual(edge.inference_rule, "unique-package-provider-match")
        self.assertLess(edge.confidence, 1.0)
        self.assertEqual(len(edge.evidence), 2)

        declared = [
            item
            for item in topology.edges.values()
            if item.relation is RelationType.DECLARES_DEPENDENCY
        ]
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0].disposition, RelationDisposition.OBSERVED)

    def test_ambiguous_provider_does_not_infer_repo_dependency(self):
        app = observation(
            "acme/app",
            "a" * 40,
            {"package.json": '{"name":"app","dependencies":{"shared":"1"}}'},
        )
        first = observation(
            "acme/one",
            "b" * 40,
            {"package.json": '{"name":"shared"}'},
        )
        second = observation(
            "acme/two",
            "c" * 40,
            {"package.json": '{"name":"shared"}'},
        )
        topology = bootstrap_portfolio([app, first, second])

        dependencies = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.DEPENDS_ON
        ]
        self.assertEqual(dependencies, [])
        self.assertTrue(
            any("ambiguous provider" in warning for warning in topology.warnings)
        )

    def test_currentness_is_exact_and_digest_changes_with_revision(self):
        first = bootstrap_portfolio(
            [observation("acme/app", "a" * 40, {})], portfolio_id="acme"
        )
        second = bootstrap_portfolio(
            [observation("acme/app", "b" * 40, {})], portfolio_id="acme"
        )
        currentness = first.currentness["repo:acme/app"]
        self.assertEqual(currentness.kind, CurrentnessKind.EXACT_REVISION)
        self.assertEqual(currentness.revision, "a" * 40)
        self.assertNotEqual(first.currentness_digest, second.currentness_digest)

    def test_local_bootstrap_reads_manifests_without_executing_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "sample"
            root.mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\nname = "sample"\ndependencies = ["other>=1"]\n',
                encoding="utf-8",
            )
            (root / "DO_NOT_EXECUTE.py").write_text(
                'raise RuntimeError("must never execute")\n',
                encoding="utf-8",
            )
            observed = observe_local_repository(root)
            topology = bootstrap_portfolio([observed])
            self.assertIn("package:python:sample", topology.nodes)


if __name__ == "__main__":
    unittest.main()
