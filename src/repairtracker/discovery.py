from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model import canonical_digest
from .system_model import FactDisposition, SystemFact, SystemModel


MARKERS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("language_ecosystem", "python"),
    "requirements.txt": ("language_ecosystem", "python"),
    "package.json": ("language_ecosystem", "node"),
    "go.mod": ("language_ecosystem", "go"),
    "Cargo.toml": ("language_ecosystem", "rust"),
    "pom.xml": ("language_ecosystem", "java"),
    "Dockerfile": ("build_surface", "docker"),
    "docker-compose.yml": ("runtime_surface", "docker-compose"),
    "docker-compose.yaml": ("runtime_surface", "docker-compose"),
    "CODEOWNERS": ("ownership_surface", "codeowners"),
}

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    model: SystemModel
    warnings: tuple[str, ...]


def _fact(path: Path, root: Path, kind: str, value: str) -> SystemFact:
    rel = path.relative_to(root).as_posix()
    fact_id = canonical_digest({"path": rel, "kind": kind, "value": value})[:24]
    return SystemFact(
        fact_id=fact_id,
        kind=kind,
        key=rel,
        value=value,
        disposition=FactDisposition.OBSERVED_SOURCE,
        provenance=rel,
    )


def _walk(root: Path, max_files: int) -> Iterable[Path]:
    count = 0
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        # Discovery does not follow symlinked files into potentially unrelated
        # filesystem subjects.
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        count += 1
        if count > max_files:
            raise RuntimeError(f"discovery file limit exceeded: {max_files}")
        yield path


def discover_repository(root: str | Path, max_files: int = 10_000) -> DiscoveryResult:
    """Read-only structural discovery.

    Discovery observes filesystem/configuration surfaces. It does not execute
    repository code and it never emits AUTHORIZED_CAPABILITY.
    """

    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"repository root is not a directory: {root_path}")

    model = SystemModel()
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for path in _walk(root_path, max_files=max_files):
        name = path.name
        rel = path.relative_to(root_path).as_posix()

        if name in MARKERS:
            kind, value = MARKERS[name]
            key = (rel, kind, value)
            if key not in seen:
                model.add_discovered_fact(_fact(path, root_path, kind, value))
                seen.add(key)

        if rel.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}:
            key = (rel, "ci_surface", "github-actions")
            if key not in seen:
                model.add_discovered_fact(_fact(path, root_path, "ci_surface", "github-actions"))
                seen.add(key)

        lowered = rel.lower()
        if "/migrations/" in f"/{lowered}" or lowered.startswith("migrations/"):
            key = (rel, "migration_surface", "migration-file")
            if key not in seen:
                model.add_discovered_fact(_fact(path, root_path, "migration_surface", "migration-file"))
                seen.add(key)

        if lowered.startswith("tests/") or "/tests/" in f"/{lowered}":
            key = (rel, "test_surface", "test-file")
            if key not in seen:
                model.add_discovered_fact(_fact(path, root_path, "test_surface", "test-file"))
                seen.add(key)

    if not model.facts:
        warnings.append("no recognized structural markers found")

    return DiscoveryResult(model=model, warnings=tuple(warnings))
