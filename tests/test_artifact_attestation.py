import unittest

from repairtracker.artifact import (
    SLSA_PROVENANCE_V1,
    ObservedArtifactDeploymentRecord,
    VerifiedArtifactProvenance,
    apply_artifact_deployment_records,
    bind_attested_runtime_artifacts,
    extract_runtime_artifact_claims,
)
from repairtracker.portfolio import RepositoryObservation, bootstrap_portfolio
from repairtracker.runtime_binding import RevisionResolution
from repairtracker.telemetry import OTelSpanObservation
from repairtracker.topology import NodeKind, RelationDisposition, RelationType


DIGEST_HEX = "d" * 64
DIGEST = "sha256:" + DIGEST_HEX
SOURCE = "abcdef1" + ("b" * 33)


class FakeResolver:
    def resolve_revision(self, repository_id, revision):
        return RevisionResolution(
            repository_id=repository_id,
            requested_revision=revision,
            resolved_revision=SOURCE,
            observed_at="2026-09-23T13:20:00+00:00",
            locator=f"https://github.com/{repository_id}/commit/{SOURCE}",
        )


class FakeVerifier:
    def __init__(self, *, digest=DIGEST, repo="acme/app", source=SOURCE):
        self.digest = digest
        self.repo = repo
        self.source = source
        self.calls = []

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        return VerifiedArtifactProvenance(
            artifact_digest=self.digest,
            repository_id=self.repo,
            source_revision=self.source,
            predicate_type=SLSA_PROVENANCE_V1,
            verifier="fixture-attestation",
            verification_ref="fixture://attestation",
            observed_at="2026-09-23T13:20:00+00:00",
            receipt_digest="f" * 64,
            signer_identity="fixture-signer",
        )


def span(**overrides):
    values = dict(
        trace_id="a" * 32,
        span_id="1" * 16,
        parent_span_id=None,
        service_name="api",
        service_namespace="shop",
        span_name="request",
        observed_at="2026-09-23T13:20:00+00:00",
        source_locator="otel://fixture",
        service_version="1.2.3",
        service_instance_id="api-1",
        deployment_environment="production",
        vcs_repository_url="https://github.com/acme/app",
        vcs_revision="abcdef1",
        container_id="container-1",
        container_image_id="sha256:" + ("c" * 64),
        container_image_name="ghcr.io/acme/app",
        container_image_repo_digests=(
            "ghcr.io/acme/app@" + DIGEST,
        ),
        oci_manifest_digest=DIGEST,
        deployment_id="deploy-42",
        deployment_name="production-api",
    )
    values.update(overrides)
    return OTelSpanObservation(**values)


class ArtifactAttestationTests(unittest.TestCase):
    def test_conflicting_repo_and_manifest_digest_fails_closed(self):
        claims, warnings = extract_runtime_artifact_claims(
            (span(oci_manifest_digest="sha256:" + ("e" * 64)),)
        )
        self.assertEqual(claims, ())
        self.assertTrue(
            any("repository and OCI manifest digests" in item for item in warnings)
        )

    def test_attested_binding_requires_instance_identity(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision="a" * 40,
            observed_at="2026-09-23T13:20:00+00:00",
            source_system="fixture",
            source_locator="fixture://repo",
            files={},
        )
        topology = bootstrap_portfolio((repo,), portfolio_id="acme")
        result = bind_attested_runtime_artifacts(
            topology,
            (span(service_instance_id=None),),
            FakeResolver(),
            FakeVerifier(),
        )
        self.assertEqual(result.verified_bindings, 0)
        self.assertTrue(any("service.instance.id" in w for w in result.warnings))

    def test_verified_chain_keeps_runtime_observation_and_attestation_distinct(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision="a" * 40,
            observed_at="2026-09-23T13:20:00+00:00",
            source_system="fixture",
            source_locator="fixture://repo",
            files={},
        )
        topology = bootstrap_portfolio((repo,), portfolio_id="acme")
        verifier = FakeVerifier()
        result = bind_attested_runtime_artifacts(
            topology,
            (span(),),
            FakeResolver(),
            verifier,
        )
        self.assertEqual(result.verified_bindings, 1)
        self.assertEqual(verifier.calls[0]["artifact_digest"], DIGEST)
        self.assertEqual(
            verifier.calls[0]["artifact_reference"],
            "oci://ghcr.io/acme/app@" + DIGEST,
        )
        self.assertEqual(verifier.calls[0]["source_revision"], SOURCE)

        self.assertTrue(
            any(node.kind is NodeKind.SERVICE_INSTANCE for node in topology.nodes.values())
        )
        runs = [
            edge for edge in topology.edges.values()
            if edge.relation is RelationType.RUNS_ARTIFACT
            and edge.source_id.startswith("service-instance:")
        ]
        built = [
            edge for edge in topology.edges.values()
            if edge.relation is RelationType.BUILT_FROM
        ]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].disposition, RelationDisposition.OBSERVED)
        self.assertEqual(
            runs[0].attributes["claim_ceiling"],
            "RUNTIME_SELF_REPORTED_ARTIFACT",
        )
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].disposition, RelationDisposition.VERIFIED)
        self.assertEqual(
            built[0].attributes["verification_ceiling"],
            "CRYPTOGRAPHIC_ARTIFACT_BUILD_PROVENANCE",
        )

    def test_verifier_cannot_substitute_artifact(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision="a" * 40,
            observed_at="2026-09-23T13:20:00+00:00",
            source_system="fixture",
            source_locator="fixture://repo",
            files={},
        )
        topology = bootstrap_portfolio((repo,), portfolio_id="acme")
        with self.assertRaises(ValueError):
            bind_attested_runtime_artifacts(
                topology,
                (span(),),
                FakeResolver(),
                FakeVerifier(digest="sha256:" + ("e" * 64)),
            )

    def test_external_deployment_record_is_observed_not_cryptographic_proof(self):
        topology = bootstrap_portfolio((), portfolio_id="test")
        record = ObservedArtifactDeploymentRecord(
            source_system="github-artifact-metadata",
            record_id="123",
            artifact_digest=DIGEST,
            logical_environment="production",
            physical_environment="us-east",
            cluster="cluster-1",
            deployment_name="api-prod",
            attestation_id="456",
            created_at="2026-09-23T12:00:00Z",
            updated_at="2026-09-23T12:05:00Z",
            locator="github://deployment/123",
            observed_at="2026-09-23T13:20:00+00:00",
            payload_digest="9" * 64,
        )
        self.assertEqual(
            apply_artifact_deployment_records(topology, (record,)),
            1,
        )
        edges = [
            edge for edge in topology.edges.values()
            if edge.relation is RelationType.DEPLOYED_TO
        ]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].disposition, RelationDisposition.OBSERVED)
        self.assertEqual(
            edges[0].attributes["claim_ceiling"],
            "EXTERNAL_ARTIFACT_DEPLOYMENT_RECORD",
        )


if __name__ == "__main__":
    unittest.main()
