import json
import subprocess
import unittest

from repairtracker.adapters.attestation_cli import (
    AttestationVerificationError,
    GitHubCLIAttestationVerifier,
)
from repairtracker.attestation import SLSA_PROVENANCE_V1


ARTIFACT_SHA = "a" * 64
SOURCE_SHA = "b" * 40


def statement():
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "artifact", "digest": {"sha256": ARTIFACT_SHA}}],
        "predicateType": SLSA_PROVENANCE_V1,
        "predicate": {
            "buildDefinition": {
                "buildType": "https://example.test/build",
                "externalParameters": {
                    "workflow": {
                        "repository": "https://github.com/acme/app"
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": "git+https://github.com/acme/app.git",
                        "digest": {"gitCommit": SOURCE_SHA},
                    }
                ],
            },
            "runDetails": {},
        },
    }


class AttestationCompletionTests(unittest.TestCase):
    def test_file_verification_defaults_to_deny_self_hosted(self):
        calls = []

        def runner(args, *, timeout):
            calls.append((args, timeout))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "verificationResult": {
                                "statement": statement(),
                                "verifiedTimestamps": [
                                    {"timestamp": "2026-09-23T13:00:00Z"}
                                ],
                            }
                        }
                    ]
                ),
                stderr="",
            )

        receipts = GitHubCLIAttestationVerifier(runner=runner).verify_file(
            artifact_path="artifact.tar.gz",
            sha256_digest=ARTIFACT_SHA,
            repository_id="acme/app",
            source_revision=SOURCE_SHA,
        )
        self.assertEqual(len(receipts), 1)
        args = calls[0][0]
        self.assertIn("artifact.tar.gz", args)
        self.assertIn("--deny-self-hosted-runners", args)
        self.assertIn("--source-digest", args)
        self.assertIn(SOURCE_SHA, args)

    def test_file_verifier_rejects_option_like_path(self):
        calls = []

        def runner(args, *, timeout):
            calls.append(args)
            raise AssertionError("runner must not execute")

        verifier = GitHubCLIAttestationVerifier(runner=runner)
        with self.assertRaises(ValueError):
            verifier.verify_file(
                artifact_path="--repo=evil/repo",
                sha256_digest=ARTIFACT_SHA,
                repository_id="acme/app",
                source_revision=SOURCE_SHA,
            )
        self.assertEqual(calls, [])

    def test_verified_output_with_wrong_subject_never_becomes_receipt(self):
        bad = statement()
        bad["subject"][0]["digest"]["sha256"] = "c" * 64

        def runner(args, *, timeout):
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [{"verificationResult": {"statement": bad}}]
                ),
                stderr="",
            )

        with self.assertRaises(AttestationVerificationError):
            GitHubCLIAttestationVerifier(runner=runner).verify_file(
                artifact_path="artifact.tar.gz",
                sha256_digest=ARTIFACT_SHA,
                repository_id="acme/app",
                source_revision=SOURCE_SHA,
            )

    def test_oci_verification_also_defaults_to_deny_self_hosted(self):
        calls = []

        def runner(args, *, timeout):
            calls.append(args)
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [{"verificationResult": {"statement": statement()}}]
                ),
                stderr="",
            )

        GitHubCLIAttestationVerifier(runner=runner).verify_oci(
            artifact_name="ghcr.io/acme/app",
            sha256_digest=ARTIFACT_SHA,
            repository_id="acme/app",
            source_revision=SOURCE_SHA,
        )
        self.assertIn("--deny-self-hosted-runners", calls[0])


if __name__ == "__main__":
    unittest.main()
