from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from repairtracker.portfolio import (
    MANIFEST_NAMES,
    RepositoryObservation,
    WorkflowObservation,
)


GITHUB_API_VERSION = "2026-03-10"
_FULL_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubReadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OwnerDiscoveryResult:
    repositories: tuple[str, ...]
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
        )
        if not allowed:
            raise ValueError(
                "GitHub read transport only permits repository-read endpoints"
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
