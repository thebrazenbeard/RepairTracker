from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import subprocess
from typing import Protocol, Sequence

from repairtracker.artifact import (
    SLSA_PROVENANCE_V1,
    VerifiedArtifactProvenance,
    normalize_sha256_digest,
)
from repairtracker.model import canonical_digest


class AttestationVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: Sequence[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def run(self, args: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                list(args),
                check=False,
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AttestationVerificationError(
                f"gh attestation verification timed out after "
                f"{self.timeout_seconds:g} seconds"
            ) from exc
        except OSError as exc:
            raise AttestationVerificationError(
                f"could not execute attestation verifier: {exc}"
            ) from exc

        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class GitHubCLIAttestationVerifier:
    """Cryptographic GitHub artifact-attestation verification via official gh CLI."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        gh_binary: str = "gh",
        signer_workflow: str | None = None,
        deny_self_hosted_runners: bool = True,
    ) -> None:
        self.runner = runner or SubprocessCommandRunner()
        self.gh_binary = gh_binary
        self.signer_workflow = signer_workflow
        self.deny_self_hosted_runners = deny_self_hosted_runners

    def verify(
        self,
        *,
        artifact_reference: str,
        artifact_digest: str,
        repository_id: str,
        source_revision: str,
    ) -> VerifiedArtifactProvenance:
        normalized = normalize_sha256_digest(artifact_digest)
        if normalized is None:
            raise ValueError("artifact_digest must be sha256")
        if not artifact_reference or artifact_reference.startswith("-"):
            raise ValueError(
                "artifact_reference must be a non-option file path or OCI reference"
            )
        if (
            repository_id.count("/") != 1
            or any(not part for part in repository_id.split("/"))
            or repository_id.startswith("-")
        ):
            raise ValueError("repository_id must be owner/repo")
        if (
            not source_revision
            or len(source_revision) < 7
            or any(ch not in "0123456789abcdefABCDEF" for ch in source_revision)
        ):
            raise ValueError("source_revision must be an exact hexadecimal revision")
        if self.signer_workflow is not None and not self.signer_workflow.strip():
            raise ValueError("signer_workflow cannot be blank")

        args = [
            self.gh_binary,
            "attestation",
            "verify",
            artifact_reference,
            "--repo",
            repository_id,
            "--source-digest",
            source_revision.lower(),
            "--predicate-type",
            SLSA_PROVENANCE_V1,
            "--format",
            "json",
        ]
        if self.signer_workflow:
            args.extend(["--signer-workflow", self.signer_workflow])
        if self.deny_self_hosted_runners:
            args.append("--deny-self-hosted-runners")

        result = self.runner.run(args)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise AttestationVerificationError(
                f"gh attestation verification failed: {message[:1200]}"
            )

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AttestationVerificationError(
                "gh attestation verification returned invalid JSON"
            ) from exc
        if not isinstance(payload, list) or not payload:
            raise AttestationVerificationError(
                "gh attestation verification returned no verified attestations"
            )

        matched = False
        signer_identity: str | None = None
        for item in payload:
            if not isinstance(item, dict):
                continue
            verification = item.get("verificationResult")
            if not isinstance(verification, dict):
                continue
            statement = verification.get("statement")
            if not isinstance(statement, dict):
                continue
            if statement.get("predicateType") != SLSA_PROVENANCE_V1:
                continue
            subjects = statement.get("subject", [])
            if not isinstance(subjects, list):
                continue
            for subject in subjects:
                if not isinstance(subject, dict):
                    continue
                digest = subject.get("digest")
                if not isinstance(digest, dict):
                    continue
                candidate = digest.get("sha256")
                if (
                    isinstance(candidate, str)
                    and normalize_sha256_digest(candidate) == normalized
                ):
                    matched = True
                    break
            if not matched:
                continue

            signature = verification.get("signature")
            if isinstance(signature, dict):
                certificate = signature.get("certificate")
                if isinstance(certificate, dict):
                    for key in (
                        "subjectAlternativeName",
                        "SubjectAlternativeName",
                        "subject",
                    ):
                        value = certificate.get(key)
                        if isinstance(value, str) and value.strip():
                            signer_identity = value.strip()
                            break
            break

        if not matched:
            raise AttestationVerificationError(
                "verified attestation output did not contain the expected artifact digest"
            )

        observed_at = datetime.now(timezone.utc).isoformat()
        receipt_digest = canonical_digest(payload)
        return VerifiedArtifactProvenance(
            artifact_digest=normalized,
            repository_id=repository_id,
            source_revision=source_revision.lower(),
            predicate_type=SLSA_PROVENANCE_V1,
            verifier="github-cli-attestation",
            verification_ref=(
                f"gh-attestation://{repository_id}/{normalized}@"
                f"{source_revision.lower()}#{receipt_digest}"
            ),
            observed_at=observed_at,
            receipt_digest=receipt_digest,
            signer_identity=signer_identity,
        )
