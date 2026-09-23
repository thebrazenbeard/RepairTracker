import json
import unittest

from repairtracker.adapters.attestation import (
    AttestationVerificationError,
    CommandResult,
    GitHubCLIAttestationVerifier,
)
from repairtracker.artifact import SLSA_PROVENANCE_V1


DIGEST = "sha256:" + ("a" * 64)
SOURCE = "b" * 40


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, args):
        self.calls.append(tuple(args))
        return self.result


def verified_output():
    return json.dumps(
        [
            {
                "attestation": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"},
                "verificationResult": {
                    "statement": {
                        "_type": "https://in-toto.io/Statement/v1",
                        "subject": [
                            {
                                "name": "artifact",
                                "digest": {"sha256": "a" * 64},
                            }
                        ],
                        "predicateType": SLSA_PROVENANCE_V1,
                        "predicate": {},
                    },
                    "signature": {
                        "certificate": {
                            "subjectAlternativeName": (
                                "https://github.com/acme/build/.github/workflows/release.yml"
                            )
                        }
                    },
                    "verifiedTimestamps": [{"type": "transparency-log"}],
                },
            }
        ]
    )


class AttestationAdapterTests(unittest.TestCase):
    def test_verifier_enforces_repository_source_predicate_and_runner_policy(self):
        runner = FakeRunner(CommandResult(0, verified_output(), ""))
        verifier = GitHubCLIAttestationVerifier(
            runner=runner,
            signer_workflow="acme/build/.github/workflows/release.yml",
        )
        receipt = verifier.verify(
            artifact_reference="artifact.bin",
            artifact_digest=DIGEST,
            repository_id="acme/app",
            source_revision=SOURCE,
        )

        command = runner.calls[0]
        self.assertIn("--repo", command)
        self.assertIn("acme/app", command)
        self.assertIn("--source-digest", command)
        self.assertIn(SOURCE, command)
        self.assertIn("--predicate-type", command)
        self.assertIn(SLSA_PROVENANCE_V1, command)
        self.assertIn("--signer-workflow", command)
        self.assertIn("--deny-self-hosted-runners", command)
        self.assertEqual(receipt.artifact_digest, DIGEST)
        self.assertEqual(receipt.source_revision, SOURCE)

    def test_nonzero_verifier_exit_is_not_promoted(self):
        verifier = GitHubCLIAttestationVerifier(
            runner=FakeRunner(CommandResult(1, "", "verification failed"))
        )
        with self.assertRaises(AttestationVerificationError):
            verifier.verify(
                artifact_reference="artifact.bin",
                artifact_digest=DIGEST,
                repository_id="acme/app",
                source_revision=SOURCE,
            )

    def test_verified_output_must_contain_expected_subject_digest(self):
        payload = json.loads(verified_output())
        payload[0]["verificationResult"]["statement"]["subject"][0]["digest"]["sha256"] = "c" * 64
        verifier = GitHubCLIAttestationVerifier(
            runner=FakeRunner(CommandResult(0, json.dumps(payload), ""))
        )
        with self.assertRaises(AttestationVerificationError):
            verifier.verify(
                artifact_reference="artifact.bin",
                artifact_digest=DIGEST,
                repository_id="acme/app",
                source_revision=SOURCE,
            )

    def test_option_like_artifact_path_is_rejected_before_runner(self):
        runner = FakeRunner(CommandResult(0, verified_output(), ""))
        verifier = GitHubCLIAttestationVerifier(runner=runner)
        with self.assertRaises(ValueError):
            verifier.verify(
                artifact_reference="--repo=evil/repo",
                artifact_digest=DIGEST,
                repository_id="acme/app",
                source_revision=SOURCE,
            )
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
