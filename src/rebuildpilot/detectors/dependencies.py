"""Dependency manifest, lockfile, project type, and language detection."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, ProjectFile, Severity
from .common import make_finding
from .context import ScanContext


MANIFESTS: dict[str, tuple[str, ...]] = {
    "Python": ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"),
    "JavaScript": ("package.json",),
    "TypeScript": ("package.json", "tsconfig.json"),
    "Go": ("go.mod",),
    "Rust": ("Cargo.toml",),
    "Java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "Ruby": ("Gemfile",),
    "PHP": ("composer.json",),
}

LOCKFILES = {
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
    "requirements.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "go.sum",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
    "gradle.lockfile",
}

EXTENSION_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
}


class DependencyResult(BaseModel):
    manifests: list[str]
    lockfiles: list[str]
    project_type: str
    languages: list[str]
    findings: list[Finding]


def _file_names(context: ScanContext) -> dict[str, ProjectFile]:
    return {Path(item.relative_path).name.lower(): item for item in context.files}


def _parse_manifest_error(item: ProjectFile) -> Finding | None:
    if item.text is None:
        return None
    suffix = Path(item.relative_path).suffix.lower()
    try:
        if Path(item.relative_path).name.lower() == "package.json":
            json.loads(item.text)
        elif suffix == ".toml":
            tomllib.loads(item.text)
    except (ValueError, tomllib.TOMLDecodeError) as error:
        return make_finding(
            "RP-INPUT-002",
            Severity.medium,
            "Malformed dependency manifest",
            f"{item.relative_path} could not be parsed: {error}",
            "Fix the manifest syntax so dependency tooling can read it deterministically.",
            item.relative_path,
        )
    return None


def detect(context: ScanContext) -> DependencyResult:
    by_name = _file_names(context)
    manifests: list[str] = []
    for names in MANIFESTS.values():
        for name in names:
            item = by_name.get(name.lower())
            if item and item.relative_path not in manifests:
                manifests.append(item.relative_path)

    lockfiles = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).name in LOCKFILES
        or Path(item.relative_path).name.lower() in {name.lower() for name in LOCKFILES}
    )
    languages = set()
    for language, names in MANIFESTS.items():
        if any(Path(path).name.lower() in {name.lower() for name in names} for path in manifests):
            languages.add(language)
    for item in context.files:
        language = EXTENSION_LANGUAGES.get(Path(item.relative_path).suffix.lower())
        if language:
            languages.add(language)
    # A package.json with tsconfig is most usefully described as TypeScript.
    if "TypeScript" in languages:
        languages.discard("JavaScript")

    findings: list[Finding] = []
    for item in context.files:
        if Path(item.relative_path).name.lower() in {name.lower() for names in MANIFESTS.values() for name in names}:
            parse_error = _parse_manifest_error(item)
            if parse_error:
                findings.append(parse_error)

    if manifests and not lockfiles:
        findings.append(
            make_finding(
                "RP-DEPS-001",
                Severity.high,
                "Dependency manifest has no lockfile",
                "A dependency manifest was found, but no recognized lockfile pins transitive versions.",
                "Generate and commit the lockfile used by the project's package manager.",
            )
        )
    elif lockfiles:
        findings.append(
            make_finding(
                "RP-DEPS-002",
                Severity.info,
                "Dependency lockfile detected",
                f"Recognized lockfile(s): {', '.join(lockfiles)}.",
                "Keep the lockfile synchronized with the dependency manifest.",
            )
        )
    if not manifests:
        findings.append(
            make_finding(
                "RP-DEPS-003",
                Severity.info,
                "No dependency manifest detected",
                "No supported dependency manifest was found; this may be correct for a dependency-free project.",
                "If the project has dependencies, add the package-manager manifest and its lockfile.",
            )
        )

    if "TypeScript" in languages:
        project_type = "TypeScript"
    elif manifests:
        project_type = next(
            (language for language, names in MANIFESTS.items() if any(Path(path).name.lower() in {name.lower() for name in names} for path in manifests)),
            "multi-language",
        )
    elif languages:
        project_type = "source project"
    else:
        project_type = "unknown"
    return DependencyResult(
        manifests=sorted(manifests),
        lockfiles=lockfiles,
        project_type=project_type,
        languages=sorted(languages),
        findings=findings,
    )
