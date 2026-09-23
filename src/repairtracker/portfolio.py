from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tomllib
from typing import Iterable, Mapping

from .model import EvidenceClass, canonical_digest
from .topology import (
    CurrentnessEvidence,
    CurrentnessKind,
    EvidencePointer,
    NodeKind,
    PortfolioTopology,
    RelationDisposition,
    RelationType,
    TopologyEdge,
    TopologyNode,
    topology_edge_id,
)


MANIFEST_NAMES = frozenset({"pyproject.toml", "package.json", "go.mod", "Cargo.toml"})
BUILD_MARKERS = frozenset({"Dockerfile", "docker-compose.yml", "docker-compose.yaml"})
IGNORED_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
)


@dataclass(frozen=True, slots=True)
class WorkflowObservation:
    name: str
    path: str
    workflow_id: str | None = None
    state: str | None = None


@dataclass(frozen=True, slots=True)
class RepositoryObservation:
    repository_id: str
    default_branch: str | None
    revision: str | None
    observed_at: str
    source_system: str
    source_locator: str
    files: Mapping[str, str]
    tree_paths: tuple[str, ...] = ()
    workflows: tuple[WorkflowObservation, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def currentness(self) -> CurrentnessEvidence:
        kind = (
            CurrentnessKind.EXACT_REVISION
            if self.revision
            else CurrentnessKind.OBSERVED_UNPINNED
        )
        return CurrentnessEvidence(
            source_system=self.source_system,
            subject_id=f"repo:{self.repository_id}",
            observed_at=self.observed_at,
            kind=kind,
            revision=self.revision,
            locator=self.source_locator,
        )

    @property
    def evidence(self) -> EvidencePointer:
        payload = {
            "repository_id": self.repository_id,
            "default_branch": self.default_branch,
            "revision": self.revision,
            "tree_paths": sorted(self.tree_paths),
            "files": {
                path: canonical_digest(text)
                for path, text in sorted(self.files.items())
            },
        }
        return EvidencePointer(
            source_system=self.source_system,
            locator=self.source_locator,
            subject_ref=self.revision,
            observed_at=self.observed_at,
            evidence_class=EvidenceClass.OBSERVED,
            payload_digest=canonical_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    ecosystem: str
    name: str
    manifest_path: str


@dataclass(frozen=True, slots=True)
class DependencyDeclaration:
    ecosystem: str
    name: str
    manifest_path: str
    scope: str


def _normalize_package(ecosystem: str, name: str) -> str:
    value = name.strip()
    if ecosystem in {"python", "cargo"}:
        value = re.sub(r"[-_.]+", "-", value).lower()
    return value


def _python_dependency_name(spec: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return match.group(1) if match else None


def _parse_pyproject(path: str, text: str) -> tuple[list[PackageIdentity], list[DependencyDeclaration]]:
    data = tomllib.loads(text)
    identities: list[PackageIdentity] = []
    dependencies: list[DependencyDeclaration] = []

    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            identities.append(
                PackageIdentity("python", _normalize_package("python", name), path)
            )
        for item in project.get("dependencies", []) or []:
            if not isinstance(item, str):
                continue
            dep = _python_dependency_name(item)
            if dep:
                dependencies.append(
                    DependencyDeclaration(
                        "python",
                        _normalize_package("python", dep),
                        path,
                        "runtime",
                    )
                )

        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group, values in optional.items():
                if not isinstance(values, list):
                    continue
                for item in values:
                    if not isinstance(item, str):
                        continue
                    dep = _python_dependency_name(item)
                    if dep:
                        dependencies.append(
                            DependencyDeclaration(
                                "python",
                                _normalize_package("python", dep),
                                path,
                                f"optional:{group}",
                            )
                        )

    return identities, dependencies


def _parse_package_json(path: str, text: str) -> tuple[list[PackageIdentity], list[DependencyDeclaration]]:
    data = json.loads(text)
    identities: list[PackageIdentity] = []
    dependencies: list[DependencyDeclaration] = []

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        identities.append(PackageIdentity("node", name.strip(), path))

    for field_name, scope in (
        ("dependencies", "runtime"),
        ("devDependencies", "development"),
        ("peerDependencies", "peer"),
        ("optionalDependencies", "optional"),
    ):
        values = data.get(field_name, {})
        if not isinstance(values, dict):
            continue
        for dep_name in values:
            if isinstance(dep_name, str) and dep_name.strip():
                dependencies.append(
                    DependencyDeclaration("node", dep_name.strip(), path, scope)
                )

    return identities, dependencies


def _parse_go_mod(path: str, text: str) -> tuple[list[PackageIdentity], list[DependencyDeclaration]]:
    identities: list[PackageIdentity] = []
    dependencies: list[DependencyDeclaration] = []

    module_match = re.search(r"(?m)^\s*module\s+(\S+)", text)
    if module_match:
        identities.append(PackageIdentity("go", module_match.group(1), path))

    in_require = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line == "require (":
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue
        if line.startswith("require "):
            parts = line.split()
            if len(parts) >= 2:
                dependencies.append(
                    DependencyDeclaration("go", parts[1], path, "runtime")
                )
            continue
        if in_require:
            parts = line.split()
            if parts:
                dependencies.append(
                    DependencyDeclaration("go", parts[0], path, "runtime")
                )

    return identities, dependencies


def _parse_cargo(path: str, text: str) -> tuple[list[PackageIdentity], list[DependencyDeclaration]]:
    data = tomllib.loads(text)
    identities: list[PackageIdentity] = []
    dependencies: list[DependencyDeclaration] = []

    package = data.get("package")
    if isinstance(package, dict):
        name = package.get("name")
        if isinstance(name, str) and name.strip():
            identities.append(
                PackageIdentity("cargo", _normalize_package("cargo", name), path)
            )

    for field_name, scope in (
        ("dependencies", "runtime"),
        ("dev-dependencies", "development"),
        ("build-dependencies", "build"),
    ):
        values = data.get(field_name, {})
        if not isinstance(values, dict):
            continue
        for dep_name in values:
            if isinstance(dep_name, str) and dep_name.strip():
                dependencies.append(
                    DependencyDeclaration(
                        "cargo",
                        _normalize_package("cargo", dep_name),
                        path,
                        scope,
                    )
                )

    return identities, dependencies


def parse_manifest(path: str, text: str) -> tuple[list[PackageIdentity], list[DependencyDeclaration]]:
    name = Path(path).name
    if name == "pyproject.toml":
        return _parse_pyproject(path, text)
    if name == "package.json":
        return _parse_package_json(path, text)
    if name == "go.mod":
        return _parse_go_mod(path, text)
    if name == "Cargo.toml":
        return _parse_cargo(path, text)
    return [], []


def _package_node_id(ecosystem: str, name: str) -> str:
    return f"package:{ecosystem}:{name}"


def _edge_evidence(
    observation: RepositoryObservation,
    path: str,
    payload: object,
) -> EvidencePointer:
    locator = f"{observation.source_locator}#{path}"
    return EvidencePointer(
        source_system=observation.source_system,
        locator=locator,
        subject_ref=observation.revision,
        observed_at=observation.observed_at,
        evidence_class=EvidenceClass.OBSERVED,
        payload_digest=canonical_digest(payload),
    )


def bootstrap_portfolio(
    observations: Iterable[RepositoryObservation],
    portfolio_id: str = "default",
) -> PortfolioTopology:
    observations = tuple(observations)
    topology = PortfolioTopology(portfolio_id=portfolio_id)

    portfolio_node_id = f"portfolio:{portfolio_id}"
    topology.add_node(
        TopologyNode(
            node_id=portfolio_node_id,
            kind=NodeKind.PORTFOLIO,
            label=portfolio_id,
        )
    )

    seen_repositories: set[str] = set()
    package_providers: dict[str, list[tuple[str, EvidencePointer]]] = {}
    dependency_edges: list[tuple[str, str, DependencyDeclaration, EvidencePointer]] = []

    for observation in observations:
        if observation.repository_id in seen_repositories:
            raise ValueError(f"duplicate repository observation: {observation.repository_id}")
        seen_repositories.add(observation.repository_id)

        repo_node_id = f"repo:{observation.repository_id}"
        topology.add_node(
            TopologyNode(
                node_id=repo_node_id,
                kind=NodeKind.REPOSITORY,
                label=observation.repository_id,
                attributes={
                    "default_branch": observation.default_branch,
                    "revision": observation.revision,
                    "source_system": observation.source_system,
                },
                evidence=(observation.evidence,),
            )
        )
        topology.bind_currentness(observation.currentness)

        topology.add_edge(
            TopologyEdge(
                edge_id=topology_edge_id(
                    portfolio_node_id,
                    repo_node_id,
                    RelationType.CONTAINS,
                    RelationDisposition.OBSERVED,
                ),
                source_id=portfolio_node_id,
                target_id=repo_node_id,
                relation=RelationType.CONTAINS,
                disposition=RelationDisposition.OBSERVED,
                confidence=1.0,
                evidence=(observation.evidence,),
            )
        )

        for warning in observation.warnings:
            topology.warnings.append(f"{observation.repository_id}: {warning}")

        for workflow in observation.workflows:
            workflow_node_id = (
                f"workflow:{observation.repository_id}:{workflow.path}"
            )
            evidence = _edge_evidence(
                observation,
                workflow.path,
                {
                    "name": workflow.name,
                    "path": workflow.path,
                    "id": workflow.workflow_id,
                    "state": workflow.state,
                },
            )
            topology.add_node(
                TopologyNode(
                    node_id=workflow_node_id,
                    kind=NodeKind.WORKFLOW,
                    label=workflow.name,
                    attributes={
                        "path": workflow.path,
                        "workflow_id": workflow.workflow_id,
                        "state": workflow.state,
                    },
                    evidence=(evidence,),
                )
            )
            topology.add_edge(
                TopologyEdge(
                    edge_id=topology_edge_id(
                        repo_node_id,
                        workflow_node_id,
                        RelationType.CONTAINS,
                        RelationDisposition.OBSERVED,
                    ),
                    source_id=repo_node_id,
                    target_id=workflow_node_id,
                    relation=RelationType.CONTAINS,
                    disposition=RelationDisposition.OBSERVED,
                    confidence=1.0,
                    evidence=(evidence,),
                )
            )

        for path in observation.tree_paths:
            path_obj = Path(path)
            lowered = path.lower()
            if (
                lowered.startswith("tests/")
                or "/tests/" in f"/{lowered}"
                or path_obj.name.startswith("test_")
            ):
                node_id = f"test:{observation.repository_id}:{path}"
                evidence = _edge_evidence(observation, path, {"path": path})
                topology.add_node(
                    TopologyNode(
                        node_id=node_id,
                        kind=NodeKind.TEST_SURFACE,
                        label=path,
                        attributes={"path": path},
                        evidence=(evidence,),
                    )
                )
                topology.add_edge(
                    TopologyEdge(
                        edge_id=topology_edge_id(
                            repo_node_id,
                            node_id,
                            RelationType.CONTAINS,
                            RelationDisposition.OBSERVED,
                        ),
                        source_id=repo_node_id,
                        target_id=node_id,
                        relation=RelationType.CONTAINS,
                        disposition=RelationDisposition.OBSERVED,
                        confidence=1.0,
                        evidence=(evidence,),
                    )
                )
            if path_obj.name in BUILD_MARKERS:
                node_id = f"build:{observation.repository_id}:{path}"
                evidence = _edge_evidence(observation, path, {"path": path})
                topology.add_node(
                    TopologyNode(
                        node_id=node_id,
                        kind=NodeKind.BUILD_SURFACE,
                        label=path,
                        attributes={"path": path},
                        evidence=(evidence,),
                    )
                )
                topology.add_edge(
                    TopologyEdge(
                        edge_id=topology_edge_id(
                            repo_node_id,
                            node_id,
                            RelationType.CONTAINS,
                            RelationDisposition.OBSERVED,
                        ),
                        source_id=repo_node_id,
                        target_id=node_id,
                        relation=RelationType.CONTAINS,
                        disposition=RelationDisposition.OBSERVED,
                        confidence=1.0,
                        evidence=(evidence,),
                    )
                )

        for path, text in sorted(observation.files.items()):
            if Path(path).name not in MANIFEST_NAMES:
                continue
            try:
                identities, dependencies = parse_manifest(path, text)
            except (ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
                topology.warnings.append(
                    f"{observation.repository_id}: could not parse {path}: {exc}"
                )
                continue

            for identity in identities:
                package_id = _package_node_id(identity.ecosystem, identity.name)
                evidence = _edge_evidence(
                    observation,
                    identity.manifest_path,
                    {
                        "kind": "package_identity",
                        "ecosystem": identity.ecosystem,
                        "name": identity.name,
                    },
                )
                topology.add_node(
                    TopologyNode(
                        node_id=package_id,
                        kind=NodeKind.PACKAGE,
                        label=identity.name,
                        attributes={
                            "ecosystem": identity.ecosystem,
                            "package_name": identity.name,
                        },
                        evidence=(evidence,),
                    )
                )
                edge_id = topology_edge_id(
                    repo_node_id,
                    package_id,
                    RelationType.PROVIDES,
                    RelationDisposition.OBSERVED,
                    discriminator=identity.manifest_path,
                )
                topology.add_edge(
                    TopologyEdge(
                        edge_id=edge_id,
                        source_id=repo_node_id,
                        target_id=package_id,
                        relation=RelationType.PROVIDES,
                        disposition=RelationDisposition.OBSERVED,
                        confidence=1.0,
                        evidence=(evidence,),
                        attributes={"manifest_path": identity.manifest_path},
                    )
                )
                package_providers.setdefault(package_id, []).append(
                    (repo_node_id, evidence)
                )

            for dependency in dependencies:
                package_id = _package_node_id(dependency.ecosystem, dependency.name)
                evidence = _edge_evidence(
                    observation,
                    dependency.manifest_path,
                    {
                        "kind": "dependency_declaration",
                        "ecosystem": dependency.ecosystem,
                        "name": dependency.name,
                        "scope": dependency.scope,
                    },
                )
                if package_id not in topology.nodes:
                    topology.add_node(
                        TopologyNode(
                            node_id=package_id,
                            kind=NodeKind.PACKAGE,
                            label=dependency.name,
                            attributes={
                                "ecosystem": dependency.ecosystem,
                                "package_name": dependency.name,
                            },
                            evidence=(evidence,),
                        )
                    )
                edge_id = topology_edge_id(
                    repo_node_id,
                    package_id,
                    RelationType.DECLARES_DEPENDENCY,
                    RelationDisposition.OBSERVED,
                    discriminator=f"{dependency.manifest_path}:{dependency.scope}",
                )
                topology.add_edge(
                    TopologyEdge(
                        edge_id=edge_id,
                        source_id=repo_node_id,
                        target_id=package_id,
                        relation=RelationType.DECLARES_DEPENDENCY,
                        disposition=RelationDisposition.OBSERVED,
                        confidence=1.0,
                        evidence=(evidence,),
                        attributes={
                            "manifest_path": dependency.manifest_path,
                            "scope": dependency.scope,
                        },
                    )
                )
                dependency_edges.append(
                    (repo_node_id, package_id, dependency, evidence)
                )

    for source_repo_id, package_id, dependency, declaration_evidence in dependency_edges:
        providers = package_providers.get(package_id, [])
        providers = [
            (repo_id, evidence)
            for repo_id, evidence in providers
            if repo_id != source_repo_id
        ]
        if len(providers) == 1:
            target_repo_id, provider_evidence = providers[0]
            edge = TopologyEdge(
                edge_id=topology_edge_id(
                    source_repo_id,
                    target_repo_id,
                    RelationType.DEPENDS_ON,
                    RelationDisposition.INFERRED,
                    discriminator=package_id,
                ),
                source_id=source_repo_id,
                target_id=target_repo_id,
                relation=RelationType.DEPENDS_ON,
                disposition=RelationDisposition.INFERRED,
                confidence=0.85,
                evidence=(declaration_evidence, provider_evidence),
                inference_rule="unique-package-provider-match",
                attributes={
                    "package_id": package_id,
                    "scope": dependency.scope,
                },
            )
            topology.add_edge(edge)
        elif len(providers) > 1:
            topology.warnings.append(
                f"ambiguous provider for {package_id}: "
                + ", ".join(sorted(repo_id for repo_id, _ in providers))
            )

    return topology


def _resolve_git_dir(root: Path) -> Path | None:
    dotgit = root / ".git"
    if dotgit.is_dir():
        return dotgit
    if dotgit.is_file():
        text = dotgit.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            candidate = Path(text.split(":", 1)[1].strip())
            if not candidate.is_absolute():
                candidate = (root / candidate).resolve()
            return candidate
    return None


def _read_local_git_revision(root: Path) -> tuple[str | None, str | None]:
    git_dir = _resolve_git_dir(root)
    if git_dir is None:
        return None, None
    head_file = git_dir / "HEAD"
    if not head_file.exists():
        return None, None
    head = head_file.read_text(encoding="utf-8", errors="replace").strip()
    if not head.startswith("ref:"):
        return head or None, None

    ref = head.split(":", 1)[1].strip()
    ref_file = git_dir / ref
    if ref_file.exists():
        revision = ref_file.read_text(encoding="utf-8", errors="replace").strip()
    else:
        revision = None
        packed = git_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    revision = parts[0]
                    break

    branch = ref.removeprefix("refs/heads/")
    return revision, branch


def observe_local_repository(
    path: str | Path,
    repository_id: str | None = None,
    max_files: int = 10_000,
    max_manifest_bytes: int = 1_048_576,
) -> RepositoryObservation:
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")

    revision, branch = _read_local_git_revision(root)
    observed_at = datetime.now(timezone.utc).isoformat()
    files: dict[str, str] = {}
    tree_paths: list[str] = []
    warnings: list[str] = []
    count = 0

    for candidate in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in candidate.parts):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        count += 1
        if count > max_files:
            raise RuntimeError(f"portfolio discovery file limit exceeded: {max_files}")
        rel = candidate.relative_to(root).as_posix()
        tree_paths.append(rel)
        if candidate.name not in MANIFEST_NAMES:
            continue
        if candidate.stat().st_size > max_manifest_bytes:
            warnings.append(f"manifest exceeds read limit: {rel}")
            continue
        try:
            files[rel] = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"manifest is not UTF-8 text: {rel}")

    workflows: list[WorkflowObservation] = []
    for rel in tree_paths:
        if rel.startswith(".github/workflows/") and Path(rel).suffix in {".yml", ".yaml"}:
            workflows.append(WorkflowObservation(name=Path(rel).stem, path=rel))

    return RepositoryObservation(
        repository_id=repository_id or root.name,
        default_branch=branch,
        revision=revision,
        observed_at=observed_at,
        source_system="local-filesystem",
        source_locator=str(root),
        files=files,
        tree_paths=tuple(sorted(tree_paths)),
        workflows=tuple(workflows),
        warnings=tuple(warnings),
    )
