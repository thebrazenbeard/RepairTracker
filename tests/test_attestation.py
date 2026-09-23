import json
import subprocess
import unittest

from repairtracker.adapters.attestation_cli import (
    AttestationVerificationError,
    GitHubCLIAttestationVerifier,
)
from repairtracker.artifact import apply_runtime_artifact_topology
from repairtracker.attestation import (
    AttestationVerificationReceipt,
    bind_verified_artifact_provenance,
    parse_verified_slsa_provenance,
)
from repairtracker.portfolio import RepositoryObservation, bootstrap_portfolio
from repairtracker.runtime_binding import RevisionResolution
from repairtracker.telemetry import OTelSpanObservation
from repairtracker.topology import RelationDisposition, RelationType


SOURCE_SHA = "a" * 40
ARTIFACT_SHA = "d" * 64


def statement():
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": "ghcr.io/acme/api",
                "digest": {"sha256": ARTIFACT_SHA},
            }
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                "externalParameters": {
                    "workflow": {
                        "repository": "https://github.com/acme/app",
                        "ref": "refs/heads/main",
                        "path": ".github/workflows/build.yml",
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": "git+https://github.com/acme/app@refs/heads/main",
                        "digest": {"gitCommit": SOURCE_SHA},
                    }
                ],
            },
            "runDetails": {
                "builder": {
                    "id": (
                        "https://github.com/acme/app/.github/workflows/"
                        "build.yml@refs/heads/main"
                    )
                },
                "metadata": {
                    "invocationId": "https://github.com/acme/app/actions/runs/1"
                },
            },
        },
    }


def receipt(**overrides):
    values = dict(
        verifier="test-verifier",
        verified_at="2026-09-23T13:00:00+00:00",
        repository_id="acme/app",
        subject_algorithm="sha256",
        subject_digest=ARTIFACT_SHA,
        predicate_type="https://slsa.dev/provenance/v1",
        source_repository_id="acme/app",
        source_revision=SOURCE_SHA,
        statement=statement(),
        verification_locator="test://attestation",
        signer_policy="acme/app/.github/workflows/build.yml",
        witness_timestamps=("2026-09-23T12:59:00Z",),
    )
    values.update(overrides)
    return AttestationVerificationReceipt(**values)


class Resolver:
    def resolve_revision(self, repository_id, revision):
        return RevisionResolution(
            repository_id=repository_id,
            requested_revision=revision,
            resolved_revision=revision,
            observed_at="2026-09-23T13:00:01+00:00",
            locator=f"https://github.com/{repository_id}/commit/{revision}",
        )


def runtime_span():
    return OTelSpanObservation(
        trace_id="1" * 32,
        span_id="2" * 16,
        parent_span_id=None,
        service_name="api",
        service_namespace="shop",
        span_name="request",
        observed_at="2026-09-23T13:00:00+00:00",
        source_locator="otel://fixture",
        service_instance_id="api-1",
        service_version="1.2.3",
        deployment_environment="production",
        container_image_name="ghcr.io/acme/api",
        container_image_repo_digests=(
            f"ghcr.io/acme/api@sha256:{ARTIFACT_SHA}",
        ),
    )


class AttestationTests(unittest.TestCase):
    def test_slsa_parser_requires_subject_and_verified_source_match(self):
        parsed = parse_verified_slsa_provenance(receipt())
        self.assertEqual(parsed.subject_digest, ARTIFACT_SHA)
        self.assertEqual(parsed.source_repository_id, "acme/app")
        self.assertEqual(parsed.source_revision, SOURCE_SHA)

        bad = receipt(source_revision="b" * 40)
        with self.assertRaises(ValueError):
            parse_verified_slsa_provenance(bad)

    def test_verified_attestation_binds_artifact_to_exact_source(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision=SOURCE_SHA,
            observed_at="2026-09-23T13:00:00+00:00",
            source_system="fixture",
            source_locator="fixture://repo",
            files={},
        )
        topology = bootstrap_portfolio((repo,), portfolio_id="acme")
        runtime = apply_runtime_artifact_topology(topology, (runtime_span(),))
        artifact = runtime.claims[0]

        result = bind_verified_artifact_provenance(
            topology, artifact, receipt(), Resolver()
        )
        self.assertEqual(
            result.source_node_id, f"source:acme/app@{SOURCE_SHA}"
        )
        built = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.BUILT_FROM
        ]
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].disposition, RelationDisposition.VERIFIED)
        self.assertEqual(
            built[0].attributes["verification_ceiling"],
            "CRYPTO_VERIFIED_ATTESTATION_SOURCE_BINDING",
        )
        self.assertTrue(built[0].attributes["signer_workflow_enforced"])
        self.assertEqual(
            built[0].attributes["build_platform_integrity"],
            "NOT_ESTABLISHED",
        )

    def test_digest_mismatch_fails_before_provenance_binding(self):
        repo = RepositoryObservation(
            repository_id="acme/app",
            default_branch="main",
            revision=SOURCE_SHA,
            observed_at="2026-09-23T13:00:00+00:00",
            source_system="fixture",
            source_locator="fixture://repo",
            files={},
        )
        topology = bootstrap_portfolio((repo,))
        runtime = apply_runtime_artifact_topology(topology, (runtime_span(),))
        with self.assertRaises(ValueError):
            bind_verified_artifact_provenance(
                topology,
                runtime.claims[0],
                receipt(subject_digest="e" * 64),
                Resolver(),
            )

    def test_cli_verifier_enforces_repo_source_and_signer_policy(self):
        calls = []

        def fake_runner(args, *, timeout):
            calls.append((args, timeout))
            output = [
                {
                    "verificationResult": {
                        "statement": statement(),
                        "verifiedTimestamps": [
                            {"timestamp": "2026-09-23T12:59:00Z"}
                        ],
                    }
                }
            ]
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(output),
                stderr="",
            )

        verifier = GitHubCLIAttestationVerifier(runner=fake_runner)
        receipts = verifier.verify_oci(
            artifact_name="ghcr.io/acme/api",
            sha256_digest=ARTIFACT_SHA,
            repository_id="acme/app",
            source_revision=SOURCE_SHA,
            signer_workflow="acme/app/.github/workflows/build.yml",
            deny_self_hosted_runners=True,
        )
        self.assertEqual(len(receipts), 1)
        args = calls[0][0]
        self.assertIn("--repo", args)
        self.assertIn("--source-digest", args)
        self.assertIn("--signer-workflow", args)
        self.assertIn("--deny-self-hosted-runners", args)

    def test_workflow_repository_disagreement_fails_closed(self):
        bad_statement = statement()
        bad_statement["predicate"]["buildDefinition"]["externalParameters"][
            "workflow"
        ]["repository"] = "https://github.com/acme/other"
        with self.assertRaises(ValueError):
            parse_verified_slsa_provenance(receipt(statement=bad_statement))

    def test_cli_verifier_rejects_mutable_oci_tag(self):
        verifier = GitHubCLIAttestationVerifier(
            runner=lambda *args, **kwargs: None
        )
        with self.assertRaises(ValueError):
            verifier.verify_oci(
                artifact_name="ghcr.io/acme/api:latest",
                sha256_digest=ARTIFACT_SHA,
                repository_id="acme/app",
                source_revision=SOURCE_SHA,
            )

    def test_cli_verifier_failure_never_becomes_receipt(self):
        def failing(args, *, timeout):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="verification failed",
            )

        verifier = GitHubCLIAttestationVerifier(runner=failing)
        with self.assertRaises(AttestationVerificationError):
            verifier.verify_oci(
                artifact_name="ghcr.io/acme/api",
                sha256_digest=ARTIFACT_SHA,
                repository_id="acme/app",
                source_revision=SOURCE_SHA,
            )


if __name__ == "__main__":
    unittest.main()
