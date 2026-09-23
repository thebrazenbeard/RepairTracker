from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import subprocess
from typing import Callable

from repairtracker.attestation import (
    AttestationVerificationReceipt,
    SLSA_PROVENANCE_V1,
    parse_verified_slsa_provenance,
)


_REPOSITORY_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_REVISION = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class AttestationVerificationError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _run_command(
    args: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class GitHubCLIAttestationVerifier:
    """Cryptographically verify GitHub artifact attestations with gh.

    GitHub REST attestation listing is discovery only. This adapter delegates
    signature, timestamp, signer, subject, and source-digest verification to
    the GitHub CLI attestation verifier.
    """

    def __init__(
        self,
        *,
        gh_executable: str = "gh",
        timeout: float = 90.0,
        runner: CommandRunner | None = None,
    ) -> None:
        self.gh_executable = gh_executable
        self.timeout = timeout
        self.runner = runner or _run_command

    def verify_oci(
        self,
        *,
        artifact_name: str,
        sha256_digest: str,
        repository_id: str,
        source_revision: str,
        signer_workflow: str | None = None,
        deny_self_hosted_runners: bool = False,
        bundle_from_oci: bool = False,
    ) -> tuple[AttestationVerificationReceipt, ...]:
        artifact_name = artifact_name.strip()
        last_segment = artifact_name.rsplit("/", 1)[-1]
        if (
            not artifact_name
            or artifact_name.startswith("oci://")
            or "@" in artifact_name
            or "?" in artifact_name
            or "#" in artifact_name
            or ":" in last_segment
            or any(ch.isspace() for ch in artifact_name)
        ):
            raise ValueError(
                "artifact_name must be an immutable-target OCI image name "
                "without scheme, tag, or digest"
            )
        if not _SHA256.fullmatch(sha256_digest):
            raise ValueError("sha256_digest must be 64 hex characters")
        if not _REPOSITORY_ID.fullmatch(repository_id):
            raise ValueError("invalid GitHub repository_id")
        if not _GIT_REVISION.fullmatch(source_revision):
            raise ValueError("source_revision must be a full 40/64 hex revision")

        digest = sha256_digest.lower()
        source_revision = source_revision.lower()
        artifact_ref = f"oci://{artifact_name}@sha256:{digest}"
        args = [
            self.gh_executable,
            "attestation",
            "verify",
            artifact_ref,
            "--repo",
            repository_id,
            "--source-digest",
            source_revision,
            "--predicate-type",
            SLSA_PROVENANCE_V1,
            "--format",
            "json",
        ]
        signer_policy = None
        if signer_workflow is not None:
            signer_workflow = signer_workflow.strip()
            if not signer_workflow:
                raise ValueError("signer_workflow cannot be empty")
            args.extend(["--signer-workflow", signer_workflow])
            signer_policy = signer_workflow
        if deny_self_hosted_runners:
            args.append("--deny-self-hosted-runners")
        if bundle_from_oci:
            args.append("--bundle-from-oci")

        try:
            completed = self.runner(args, timeout=self.timeout)
        except FileNotFoundError as exc:
            raise AttestationVerificationError(
                f"GitHub CLI executable not found: {self.gh_executable}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AttestationVerificationError(
                "GitHub attestation verification timed out"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            if len(detail) > 1000:
                detail = detail[-1000:]
            raise AttestationVerificationError(
                "GitHub attestation verification failed"
                + (f": {detail}" if detail else "")
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AttestationVerificationError(
                "GitHub attestation verifier returned invalid JSON"
            ) from exc
        if not isinstance(payload, list) or not payload:
            raise AttestationVerificationError(
                "GitHub attestation verifier returned no verified attestations"
            )

        receipts: list[AttestationVerificationReceipt] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            verification = item.get("verificationResult")
            if not isinstance(verification, dict):
                continue
            statement = verification.get("statement")
            if not isinstance(statement, dict):
                continue

            timestamps: list[str] = []
            raw_timestamps = verification.get("verifiedTimestamps", [])
            if isinstance(raw_timestamps, list):
                for timestamp in raw_timestamps:
                    if not isinstance(timestamp, dict):
                        continue
                    value = timestamp.get("timestamp")
                    if isinstance(value, str) and value:
                        timestamps.append(value)

            receipt = AttestationVerificationReceipt(
                verifier="github-cli/gh-attestation-verify",
                verified_at=datetime.now(timezone.utc).isoformat(),
                repository_id=repository_id,
                subject_algorithm="sha256",
                subject_digest=digest,
                predicate_type=SLSA_PROVENANCE_V1,
                source_repository_id=repository_id,
                source_revision=source_revision,
                statement=statement,
                verification_locator=(
                    f"gh-attestation://{repository_id}/"
                    f"sha256:{digest}#{index}"
                ),
                signer_policy=signer_policy,
                witness_timestamps=tuple(timestamps),
            )
            parse_verified_slsa_provenance(receipt)
            receipts.append(receipt)

        if not receipts:
            raise AttestationVerificationError(
                "verified output contained no usable SLSA statements"
            )
        return tuple(receipts)
