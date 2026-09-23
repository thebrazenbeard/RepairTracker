from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from repairtracker.deployment import ObservedArtifactDeploymentRecord
from repairtracker.model import canonical_digest
from repairtracker.runtime_binding import RevisionResolution
from repairtracker.portfolio import (
    MANIFEST_NAMES,
    RepositoryObservation,
    WorkflowObservation,
)


GITHUB_API_VERSION = "2026-03-10"
_FULL_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubReadError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class OwnerDiscoveryResult:
    repositories: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitHubRepairSignal:
    kind: str
    repository_id: str
    external_id: str
    title: str
    state: str
    locator: str
    observed_at: str
    subject_ref: str | None
    payload_digest: str
    repository_stable_id: int | None = None


@dataclass(frozen=True, slots=True)
class GitHubSignalResult:
    signals: tuple[GitHubRepairSignal, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitHubAttestationReference:
    repository_id: str
    subject_digest: str
    bundle_url: str
    initiator: str | None


@dataclass(frozen=True, slots=True)
class GitHubAttestationIndexResult:
    references: tuple[GitHubAttestationReference, ...]
    warnings: tuple[str, ...] = ()


class JSONTransport(Protocol):
    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any: ...


class UrllibGitHubReadTransport:
    """Small read-only GitHub REST transport.

    This transport exposes GET only. It cannot create a write request through
    its public interface.
    """

    def __init__(
        self,
        token: str | None = None,
        api_version: str = GITHUB_API_VERSION,
        base_url: str = "https://api.github.com",
        timeout: float = 20.0,
    ) -> None:
        if base_url.rstrip("/") != "https://api.github.com":
            raise ValueError("GitHub transport is restricted to https://api.github.com")
        self._token = token
        self._api_version = api_version
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        allowed = (
            path.startswith("/repos/")
            or re.fullmatch(r"/users/[A-Za-z0-9_.-]+/repos", path)
            or re.fullmatch(r"/orgs/[A-Za-z0-9_.-]+/repos", path)
            or re.fullmatch(
                r"/orgs/[A-Za-z0-9_.-]+/artifacts/sha256:[0-9a-fA-F]{64}/metadata/deployment-records",
                path,
            )
            or path == "/user/repos"
        )
        if not allowed:
            raise ValueError(
                "GitHub read transport only permits configured read-only endpoints"
            )
        url = f"{self._base_url}{path}"
        if query:
            url += "?" + urlencode(query)

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
            "User-Agent": "RepairTracker",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request = Request(url=url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GitHubReadError(
                f"GitHub GET failed for {path}: {exc}",
                status_code=exc.code,
            ) from exc
        except Exception as exc:
            raise GitHubReadError(f"GitHub GET failed for {path}: {exc}") from exc


class GitHubReadClient:
    def __init__(
        self,
        transport: JSONTransport | None = None,
        token: str | None = None,
        max_manifest_bytes: int = 1_048_576,
        max_manifests: int = 200,
    ) -> None:
        self.transport = transport or UrllibGitHubReadTransport(token=token)
        self.max_manifest_bytes = max_manifest_bytes
        self.max_manifests = max_manifests

    @staticmethod
    def token_from_env(name: str = "GITHUB_TOKEN") -> str | None:
        return os.environ.get(name)

    def list_owner_repositories(
        self,
        owner: str,
        owner_kind: str = "user",
        *,
        include_archived: bool = False,
        include_forks: bool = False,
        max_repositories: int = 200,
    ) -> OwnerDiscoveryResult:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner):
            raise ValueError(f"invalid GitHub owner name: {owner!r}")
        if owner_kind not in {"user", "org"}:
            raise ValueError("owner_kind must be 'user' or 'org'")
        if max_repositories < 1:
            raise ValueError("max_repositories must be positive")

        prefix = "users" if owner_kind == "user" else "orgs"
        path = f"/{prefix}/{quote(owner, safe='')}/repos"
        repositories: list[str] = []
        warnings: list[str] = []

        for page in range(1, 101):
            query = {
                "per_page": "100",
                "page": str(page),
                "sort": "full_name",
                "direction": "asc",
            }
            if owner_kind == "org":
                query["type"] = "all"

            payload = self.transport.get_json(path, query)
            if not isinstance(payload, list):
                raise GitHubReadError(
                    f"invalid repository-list response for {owner_kind} {owner}"
                )

            for item in payload:
                if not isinstance(item, dict):
                    continue
                full_name = item.get("full_name")
                if not isinstance(full_name, str) or not _FULL_NAME.fullmatch(full_name):
                    continue
                if item.get("archived") is True and not include_archived:
                    continue
                if item.get("fork") is True and not include_forks:
                    continue
                repositories.append(full_name)
                if len(repositories) >= max_repositories:
                    warnings.append(
                        "repository discovery limit reached; result may be incomplete"
                    )
                    return OwnerDiscoveryResult(
                        repositories=tuple(repositories),
                        warnings=tuple(warnings),
                    )

            if len(payload) < 100:
                return OwnerDiscoveryResult(
                    repositories=tuple(repositories),
                    warnings=tuple(warnings),
                )

        warnings.append(
            "repository pagination ceiling reached; result may be incomplete"
        )
        return OwnerDiscoveryResult(
            repositories=tuple(repositories),
            warnings=tuple(warnings),
        )

    def list_authenticated_repositories(
        self,
        *,
        include_archived: bool = False,
        include_forks: bool = False,
        max_repositories: int = 200,
    ) -> OwnerDiscoveryResult:
        if max_repositories < 1:
            raise ValueError("max_repositories must be positive")

        repositories: list[str] = []
        warnings: list[str] = []
        for page in range(1, 101):
            payload = self.transport.get_json(
                "/user/repos",
                {
                    "per_page": "100",
                    "page": str(page),
                    "visibility": "all",
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "full_name",
                    "direction": "asc",
                },
            )
            if not isinstance(payload, list):
                raise GitHubReadError(
                    "invalid authenticated repository-list response"
                )
            for item in payload:
                if not isinstance(item, dict):
                    continue
                full_name = item.get("full_name")
                if not isinstance(full_name, str) or not _FULL_NAME.fullmatch(full_name):
                    continue
                if item.get("archived") is True and not include_archived:
                    continue
                if item.get("fork") is True and not include_forks:
                    continue
                repositories.append(full_name)
                if len(repositories) >= max_repositories:
                    warnings.append(
                        "authenticated repository discovery limit reached; "
                        "result may be incomplete"
                    )
                    return OwnerDiscoveryResult(
                        repositories=tuple(repositories),
                        warnings=tuple(warnings),
                    )
            if len(payload) < 100:
                return OwnerDiscoveryResult(
                    repositories=tuple(repositories),
                    warnings=tuple(warnings),
                )

        warnings.append(
            "authenticated repository pagination ceiling reached; "
            "result may be incomplete"
        )
        return OwnerDiscoveryResult(
            repositories=tuple(repositories),
            warnings=tuple(warnings),
        )

    def observe_authenticated_portfolio(
        self,
        *,
        include_archived: bool = False,
        include_forks: bool = False,
        max_repositories: int = 200,
    ) -> tuple[tuple[RepositoryObservation, ...], tuple[str, ...]]:
        discovery = self.list_authenticated_repositories(
            include_archived=include_archived,
            include_forks=include_forks,
            max_repositories=max_repositories,
        )
        observations = tuple(
            self.observe_repository(repository)
            for repository in discovery.repositories
        )
        return observations, discovery.warnings

    def observe_owner_portfolio(
        self,
        owner: str,
        owner_kind: str = "user",
        *,
        include_archived: bool = False,
        include_forks: bool = False,
        max_repositories: int = 200,
    ) -> tuple[tuple[RepositoryObservation, ...], tuple[str, ...]]:
        discovery = self.list_owner_repositories(
            owner,
            owner_kind,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repositories=max_repositories,
        )
        observations = tuple(
            self.observe_repository(repository)
            for repository in discovery.repositories
        )
        return observations, discovery.warnings

    def _list_bounded(
        self,
        path: str,
        *,
        base_query: dict[str, str],
        max_items: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            query = {**base_query, "per_page": "100", "page": str(page)}
            payload = self.transport.get_json(path, query)
            if not isinstance(payload, list):
                raise GitHubReadError(f"invalid list response for {path}")
            for item in payload:
                if isinstance(item, dict):
                    items.append(item)
                    if len(items) >= max_items:
                        return items, True
            if len(payload) < 100:
                return items, False
        return items, True

    def observe_repair_signals(
        self,
        full_name: str,
        *,
        max_items_per_kind: int = 200,
    ) -> GitHubSignalResult:
        """Read candidate repair signals without promoting them to incidents."""

        if not _FULL_NAME.fullmatch(full_name):
            raise ValueError(f"invalid GitHub repository name: {full_name!r}")
        encoded = "/".join(quote(part, safe="") for part in full_name.split("/"))
        repository_payload = self.transport.get_json(f"/repos/{encoded}")
        stable_repository_id = repository_payload.get("id")
        if not isinstance(stable_repository_id, int):
            stable_repository_id = None

        observed_at = datetime.now(timezone.utc).isoformat()
        warnings: list[str] = []
        if stable_repository_id is None:
            warnings.append(
                "GitHub repository numeric ID unavailable; signal identity "
                "will fall back to rename-sensitive repository name"
            )
        signals: list[GitHubRepairSignal] = []

        issues, issue_limited = self._list_bounded(
            f"/repos/{encoded}/issues",
            base_query={"state": "open", "sort": "updated", "direction": "desc"},
            max_items=max_items_per_kind,
        )
        if issue_limited:
            warnings.append("issue signal limit reached; result may be incomplete")
        for item in issues:
            if "pull_request" in item:
                continue
            number = item.get("number")
            title = item.get("title")
            html_url = item.get("html_url")
            if not isinstance(number, int) or not isinstance(title, str):
                continue
            locator = (
                html_url
                if isinstance(html_url, str)
                else f"https://github.com/{full_name}/issues/{number}"
            )
            signals.append(
                GitHubRepairSignal(
                    kind="ISSUE",
                    repository_id=full_name,
                    external_id=str(number),
                    title=title,
                    state=str(item.get("state") or "open"),
                    locator=locator,
                    observed_at=observed_at,
                    subject_ref=None,
                    payload_digest=canonical_digest(
                        {
                            "repository_id": full_name,
                            "repository_stable_id": stable_repository_id,
                            "number": number,
                            "title": title,
                            "state": item.get("state"),
                            "updated_at": item.get("updated_at"),
                        }
                    ),
                    repository_stable_id=stable_repository_id,
                )
            )

        pulls, pull_limited = self._list_bounded(
            f"/repos/{encoded}/pulls",
            base_query={"state": "open", "sort": "updated", "direction": "desc"},
            max_items=max_items_per_kind,
        )
        if pull_limited:
            warnings.append("pull-request signal limit reached; result may be incomplete")
        for item in pulls:
            number = item.get("number")
            title = item.get("title")
            html_url = item.get("html_url")
            head = item.get("head", {})
            head_sha = head.get("sha") if isinstance(head, dict) else None
            if not isinstance(number, int) or not isinstance(title, str):
                continue
            locator = (
                html_url
                if isinstance(html_url, str)
                else f"https://github.com/{full_name}/pull/{number}"
            )
            signals.append(
                GitHubRepairSignal(
                    kind="PULL_REQUEST",
                    repository_id=full_name,
                    external_id=str(number),
                    title=title,
                    state=str(item.get("state") or "open"),
                    locator=locator,
                    observed_at=observed_at,
                    subject_ref=head_sha if isinstance(head_sha, str) else None,
                    payload_digest=canonical_digest(
                        {
                            "repository_id": full_name,
                            "repository_stable_id": stable_repository_id,
                            "number": number,
                            "title": title,
                            "state": item.get("state"),
                            "head_sha": head_sha,
                            "updated_at": item.get("updated_at"),
                        }
                    ),
                    repository_stable_id=stable_repository_id,
                )
            )

        workflow_items: list[dict[str, Any]] = []
        workflow_limited = False
        for page in range(1, 101):
            payload = self.transport.get_json(
                f"/repos/{encoded}/actions/runs",
                {"per_page": "100", "page": str(page)},
            )
            if not isinstance(payload, dict):
                raise GitHubReadError(
                    f"invalid workflow-runs response for {full_name}"
                )
            raw_runs = payload.get("workflow_runs", [])
            if not isinstance(raw_runs, list):
                raise GitHubReadError(
                    f"invalid workflow-runs response for {full_name}"
                )
            for item in raw_runs:
                if isinstance(item, dict):
                    workflow_items.append(item)
                    if len(workflow_items) >= max_items_per_kind:
                        workflow_limited = True
                        break
            if workflow_limited or len(raw_runs) < 100:
                break
        if workflow_limited:
            warnings.append("workflow-run signal limit reached; result may be incomplete")

        failure_conclusions = {
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
        }
        for item in workflow_items:
            conclusion = item.get("conclusion")
            if conclusion not in failure_conclusions:
                continue
            run_id = item.get("id")
            name = item.get("name") or item.get("display_title")
            html_url = item.get("html_url")
            head_sha = item.get("head_sha")
            if not isinstance(run_id, int) or not isinstance(name, str):
                continue
            locator = (
                html_url
                if isinstance(html_url, str)
                else f"https://github.com/{full_name}/actions/runs/{run_id}"
            )
            signals.append(
                GitHubRepairSignal(
                    kind="WORKFLOW_RUN",
                    repository_id=full_name,
                    external_id=str(run_id),
                    title=name,
                    state=str(conclusion),
                    locator=locator,
                    observed_at=observed_at,
                    subject_ref=head_sha if isinstance(head_sha, str) else None,
                    payload_digest=canonical_digest(
                        {
                            "repository_id": full_name,
                            "repository_stable_id": stable_repository_id,
                            "id": run_id,
                            "name": name,
                            "conclusion": conclusion,
                            "head_sha": head_sha,
                            "event": item.get("event"),
                            "updated_at": item.get("updated_at"),
                        }
                    ),
                    repository_stable_id=stable_repository_id,
                )
            )

        return GitHubSignalResult(
            signals=tuple(signals),
            warnings=tuple(warnings),
        )

    def resolve_revision(
        self, full_name: str, revision: str
    ) -> RevisionResolution:
        if not _FULL_NAME.fullmatch(full_name):
            raise ValueError(f"invalid GitHub repository name: {full_name!r}")
        revision = revision.strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
            raise ValueError(
                "exact source binding requires an immutable-looking hex revision"
            )

        encoded = "/".join(quote(part, safe="") for part in full_name.split("/"))
        payload = self.transport.get_json(
            f"/repos/{encoded}/commits/{quote(revision, safe='')}"
        )
        sha = payload.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            raise GitHubReadError(
                f"GitHub commit response has no usable exact SHA: {full_name}@{revision}"
            )
        if not sha.lower().startswith(revision.lower()):
            raise GitHubReadError(
                f"GitHub resolved revision does not match requested prefix: "
                f"{full_name}@{revision}"
            )
        observed_at = datetime.now(timezone.utc).isoformat()
        exact = sha.lower()
        return RevisionResolution(
            repository_id=full_name,
            requested_revision=revision.lower(),
            resolved_revision=exact,
            observed_at=observed_at,
            locator=f"https://github.com/{full_name}/commit/{exact}",
        )

    def list_attestations(
        self,
        full_name: str,
        subject_digest: str,
        *,
        predicate_type: str = "provenance",
        max_results: int = 100,
    ) -> GitHubAttestationIndexResult:
        """Locate repository attestations without claiming cryptographic verification."""

        if not _FULL_NAME.fullmatch(full_name):
            raise ValueError(f"invalid GitHub repository name: {full_name!r}")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", subject_digest):
            raise ValueError("subject_digest must be sha256: followed by 64 hex chars")
        if not predicate_type.strip():
            raise ValueError("predicate_type is required")
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")

        encoded = "/".join(quote(part, safe="") for part in full_name.split("/"))
        digest = subject_digest.lower()
        try:
            payload = self.transport.get_json(
                f"/repos/{encoded}/attestations/{quote(digest, safe=':')}",
                {
                    "per_page": str(max_results),
                    "predicate_type": predicate_type,
                },
            )
        except GitHubReadError as exc:
            if exc.status_code == 404:
                return GitHubAttestationIndexResult(
                    references=(),
                    warnings=(
                        "GitHub returned 404 for the attestation subject; this "
                        "may mean no matching attestation or an inaccessible "
                        "resource, so completeness is unknown",
                    ),
                )
            raise
        if not isinstance(payload, dict):
            raise GitHubReadError(
                f"invalid attestation-index response for {full_name}"
            )
        raw = payload.get("attestations", [])
        if not isinstance(raw, list):
            raise GitHubReadError(
                f"invalid attestation collection for {full_name}"
            )

        references: list[GitHubAttestationReference] = []
        for item in raw[:max_results]:
            if not isinstance(item, dict):
                continue
            bundle_url = item.get("bundle_url")
            if not isinstance(bundle_url, str) or not bundle_url.startswith("https://"):
                continue
            initiator = item.get("initiator")
            references.append(
                GitHubAttestationReference(
                    repository_id=full_name,
                    subject_digest=digest,
                    bundle_url=bundle_url,
                    initiator=initiator if isinstance(initiator, str) else None,
                )
            )

        warnings: list[str] = []
        if len(raw) >= max_results:
            warnings.append(
                "attestation result ceiling reached; additional attestations "
                "may exist because V0 transport does not expose cursor headers"
            )
        return GitHubAttestationIndexResult(
            references=tuple(references),
            warnings=tuple(warnings),
        )

    def observe_artifact_deployments(
        self,
        organization: str,
        artifact_digest: str,
    ) -> tuple[ObservedArtifactDeploymentRecord, ...]:
        """Read GitHub artifact-metadata deployment records for one exact digest."""

        if not re.fullmatch(r"[A-Za-z0-9_.-]+", organization):
            raise ValueError(f"invalid GitHub organization: {organization!r}")
        digest = artifact_digest.strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("artifact_digest must be sha256:HEX")

        path = (
            f"/orgs/{quote(organization, safe='')}/artifacts/"
            f"{quote(digest, safe=':')}/metadata/deployment-records"
        )
        payload = self.transport.get_json(path)
        if not isinstance(payload, dict):
            raise GitHubReadError(
                f"invalid artifact deployment response for {organization}/{digest}"
            )
        records = payload.get("deployment_records", [])
        if not isinstance(records, list):
            raise GitHubReadError(
                f"invalid artifact deployment records for {organization}/{digest}"
            )

        observed_at = datetime.now(timezone.utc).isoformat()
        result: list[ObservedArtifactDeploymentRecord] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            returned_digest = item.get("digest")
            if not isinstance(returned_digest, str):
                continue
            if returned_digest.lower() != digest:
                raise GitHubReadError(
                    "artifact deployment record digest does not match request"
                )
            record_id = item.get("id")
            if record_id is None:
                continue

            attestation_id = item.get("attestation_id")
            result.append(
                ObservedArtifactDeploymentRecord(
                    source_system="github-artifact-metadata",
                    record_id=str(record_id),
                    artifact_digest=digest,
                    logical_environment=(
                        str(item["logical_environment"])
                        if item.get("logical_environment") is not None
                        else None
                    ),
                    physical_environment=(
                        str(item["physical_environment"])
                        if item.get("physical_environment") is not None
                        else None
                    ),
                    cluster=(
                        str(item["cluster"])
                        if item.get("cluster") is not None
                        else None
                    ),
                    deployment_name=(
                        str(item["deployment_name"])
                        if item.get("deployment_name") is not None
                        else None
                    ),
                    attestation_id=(
                        str(attestation_id)
                        if attestation_id is not None
                        else None
                    ),
                    created_at=(
                        str(item["created"])
                        if item.get("created") is not None
                        else None
                    ),
                    updated_at=(
                        str(item["updated_at"])
                        if item.get("updated_at") is not None
                        else None
                    ),
                    locator=(
                        f"https://github.com/orgs/{organization}/artifacts/"
                        f"{digest}#deployment-record-{record_id}"
                    ),
                    observed_at=observed_at,
                    payload_digest=canonical_digest(item),
                )
            )
        return tuple(result)

    def _repository_default_branch(self, encoded: str, full_name: str) -> str:
        repo = self.transport.get_json(f"/repos/{encoded}")
        default_branch = repo.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise GitHubReadError(f"repository has no usable default branch: {full_name}")
        return default_branch

    def _branch_revision(self, encoded: str, branch_name: str, full_name: str) -> str:
        branch = self.transport.get_json(
            f"/repos/{encoded}/branches/{quote(branch_name, safe='')}"
        )
        commit = branch.get("commit", {})
        revision = commit.get("sha")
        if not isinstance(revision, str) or not revision:
            raise GitHubReadError(f"default branch has no usable commit SHA: {full_name}")
        return revision

    def _observe_pinned(
        self,
        full_name: str,
        encoded: str,
        default_branch: str,
        revision: str,
    ) -> RepositoryObservation:
        tree = self.transport.get_json(
            f"/repos/{encoded}/git/trees/{quote(revision, safe='')}",
            {"recursive": "1"},
        )
        tree_entries = tree.get("tree", [])
        if not isinstance(tree_entries, list):
            raise GitHubReadError(f"invalid tree response for {full_name}")

        warnings: list[str] = []
        if tree.get("truncated") is True:
            warnings.append("GitHub recursive tree response was truncated")

        tree_paths: list[str] = []
        manifest_paths: list[str] = []
        for entry in tree_entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            tree_paths.append(path)
            if path.rsplit("/", 1)[-1] in MANIFEST_NAMES:
                manifest_paths.append(path)

        if len(manifest_paths) > self.max_manifests:
            warnings.append(
                f"manifest count exceeds read limit: "
                f"{len(manifest_paths)} > {self.max_manifests}"
            )
            manifest_paths = manifest_paths[: self.max_manifests]

        files: dict[str, str] = {}
        for path in manifest_paths:
            payload = self.transport.get_json(
                f"/repos/{encoded}/contents/{quote(path, safe='/')}",
                {"ref": revision},
            )
            size = payload.get("size")
            if isinstance(size, int) and size > self.max_manifest_bytes:
                warnings.append(f"manifest exceeds read limit: {path}")
                continue

            encoding = payload.get("encoding")
            content = payload.get("content")
            if encoding == "base64" and isinstance(content, str):
                raw = base64.b64decode(content, validate=False)
                if len(raw) > self.max_manifest_bytes:
                    warnings.append(f"manifest exceeds read limit: {path}")
                    continue
                try:
                    files[path] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    warnings.append(f"manifest is not UTF-8 text: {path}")
            elif isinstance(content, str):
                if len(content.encode("utf-8")) > self.max_manifest_bytes:
                    warnings.append(f"manifest exceeds read limit: {path}")
                    continue
                files[path] = content
            else:
                warnings.append(f"manifest content unavailable: {path}")

        workflows: list[WorkflowObservation] = []
        for path in tree_paths:
            if (
                path.startswith(".github/workflows/")
                and path.rsplit(".", 1)[-1] in {"yml", "yaml"}
            ):
                workflows.append(
                    WorkflowObservation(
                        name=path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                        path=path,
                    )
                )

        observed_at = datetime.now(timezone.utc).isoformat()
        return RepositoryObservation(
            repository_id=full_name,
            default_branch=default_branch,
            revision=revision,
            observed_at=observed_at,
            source_system="github-rest",
            source_locator=f"https://github.com/{full_name}/tree/{revision}",
            files=files,
            tree_paths=tuple(sorted(tree_paths)),
            workflows=tuple(workflows),
            warnings=tuple(warnings),
        )

    def observe_repository(self, full_name: str) -> RepositoryObservation:
        if not _FULL_NAME.fullmatch(full_name):
            raise ValueError(f"invalid GitHub repository name: {full_name!r}")

        encoded = "/".join(quote(part, safe="") for part in full_name.split("/"))
        retried = False

        for attempt in range(2):
            default_branch_b0 = self._repository_default_branch(encoded, full_name)
            revision_b0 = self._branch_revision(
                encoded, default_branch_b0, full_name
            )
            observation = self._observe_pinned(
                full_name,
                encoded,
                default_branch_b0,
                revision_b0,
            )
            revision_b1 = self._branch_revision(
                encoded, default_branch_b0, full_name
            )
            default_branch_b1 = self._repository_default_branch(
                encoded, full_name
            )

            if (
                revision_b0 == revision_b1
                and default_branch_b0 == default_branch_b1
            ):
                if retried:
                    observation = replace(
                        observation,
                        warnings=(
                            *observation.warnings,
                            "GitHub default-branch snapshot stabilized after one retry",
                        ),
                    )
                return observation

            if attempt == 0:
                retried = True
                continue

        raise GitHubReadError(
            f"GitHub default branch remained unstable across two reads: {full_name}"
        )
