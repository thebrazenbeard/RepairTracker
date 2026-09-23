import unittest

from repairtracker.portfolio import RepositoryObservation, bootstrap_portfolio
from repairtracker.runtime_binding import (
    RevisionResolution,
    bind_runtime_sources,
    extract_runtime_source_claims,
    github_repository_id_from_url,
)
from repairtracker.telemetry import OTelSpanObservation
from repairtracker.topology import RelationDisposition, RelationType


class FakeResolver:
    def resolve_revision(self, repository_id, revision):
        return RevisionResolution(
            repository_id=repository_id,
            requested_revision=revision,
            resolved_revision=revision + ("a" * (40 - len(revision))),
            observed_at="2026-09-23T12:00:00+00:00",
            locator=f"https://github.com/{repository_id}/commit/{revision}",
        )


def span(*, revision="abcdef1", repo="https://github.com/acme/app"):
    return OTelSpanObservation(
        trace_id="1" * 32,
        span_id="2" * 16,
        parent_span_id=None,
        service_name="api",
        service_namespace="shop",
        span_name="GET /",
        observed_at="2026-09-23T12:00:00+00:00",
        source_locator="otel://fixture",
        service_version="2026.09.23",
        service_instance_id="api-1",
        deployment_environment="production",
        vcs_repository_url=repo,
        vcs_revision=revision,
    )


class RuntimeBindingTests(unittest.TestCase):
    def test_github_url_normalization_is_strict(self):
        self.assertEqual(
            github_repository_id_from_url("https://github.com/acme/app.git"),
            "acme/app",
        )
        self.assertIsNone(
            github_repository_id_from_url("http://github.com/acme/app")
        )
        self.assertIsNone(
            github_repository_id_from_url("https://github.com/acme/app?x=1")
        )

    def test_symbolic_revision_is_not_exact_source_binding(self):
        claims, warnings = extract_runtime_source_claims((span(revision="main"),))
        self.assertEqual(claims, ())
        self.assertTrue(any("symbolic/non-exact" in item for item in warnings))

    def test_binding_separates_runtime_claim_from_repo_membership_verification(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision="f" * 40,
            observed_at="2026-09-23T12:00:00+00:00",
            source_system="fixture",
            source_locator="fixture://acme/app",
            files={},
        )
        topology = bootstrap_portfolio((repo,), portfolio_id="acme")
        result = bind_runtime_sources(topology, (span(),), FakeResolver())
        self.assertEqual(result.bound_claims, 1)

        reports = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.REPORTS_SOURCE
        ]
        membership = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.BELONGS_TO
        ]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].disposition, RelationDisposition.OBSERVED)
        self.assertEqual(
            reports[0].attributes["claim_ceiling"],
            "RUNTIME_SELF_REPORTED_SOURCE",
        )
        self.assertEqual(len(membership), 1)
        self.assertEqual(
            membership[0].disposition, RelationDisposition.VERIFIED
        )
        self.assertEqual(
            membership[0].attributes["verification_ceiling"],
            "SOURCE_REVISION_EXISTS_IN_REPOSITORY",
        )

    def test_repository_outside_portfolio_is_not_silently_added(self):
        topology = bootstrap_portfolio((), portfolio_id="empty")
        result = bind_runtime_sources(topology, (span(),), FakeResolver())
        self.assertEqual(result.bound_claims, 0)
        self.assertTrue(any("outside observed portfolio" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
