"""Filesystem inventory and orchestration for all reproducibility detectors."""

from __future__ import annotations

import os
from pathlib import Path

from .detectors import containers, dependencies, documentation, environment, git, machine_learning, paths, runtime, tests
from .detectors.common import make_finding
from .detectors.context import ScanContext
from .models import AnalysisReport, Finding, ProjectFile, Severity
from .scoring import calculate_score, with_default_deductions


IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "coverage",
}

TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".conf",
    ".csv",
    ".env",
    ".gitignore",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".kts",
    ".lock",
    ".md",
    ".py",
    ".ps1",
    ".pyi",
    ".rst",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {
    "dockerfile",
    "gemfile",
    "makefile",
    "pipfile",
    "readme",
    "readme.md",
    "requirements.txt",
    ".env",
    ".env.example",
    ".env.sample",
    ".env.template",
    ".nvmrc",
    ".node-version",
    ".python-version",
    ".tool-versions",
    "cargo.lock",
    "cargo.toml",
    "go.mod",
    "go.sum",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "rust-toolchain",
    "rust-toolchain.toml",
    "uv.lock",
    "yarn.lock",
}
TEXT_NAMES_CASEFOLD = {name.casefold() for name in TEXT_NAMES}


def _is_ignored(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return any(part.lower() in IGNORED_DIRECTORIES for part in relative_parts)


def _is_text_candidate(path: Path) -> bool:
    return path.name.casefold() in TEXT_NAMES_CASEFOLD or path.suffix.casefold() in TEXT_EXTENSIONS


def _inventory(root: Path) -> tuple[tuple[ProjectFile, ...], list[Finding], list[str], tuple[str, ...]]:
    files: list[ProjectFile] = []
    findings: list[Finding] = []
    unreadable: list[str] = []
    directories: set[str] = set()
    walk_error: OSError | None = None

    def on_walk_error(error: OSError) -> None:
        nonlocal walk_error
        walk_error = error

    try:
        walker = os.walk(root, topdown=True, onerror=on_walk_error)
        for directory, dirnames, filenames in walker:
            current = Path(directory)
            dirnames[:] = sorted(
                (name for name in dirnames if name.casefold() not in IGNORED_DIRECTORIES),
                key=str.casefold,
            )
            for name in dirnames:
                directories.add((current / name).relative_to(root).as_posix())
            for name in sorted(filenames, key=str.casefold):
                path = current / name
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                text: str | None = None
                read_error: str | None = None
                if _is_text_candidate(path):
                    try:
                        text = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as error:
                        read_error = str(error)
                        unreadable.append(relative)
                        findings.append(
                            make_finding(
                                "RP-INPUT-001",
                                Severity.medium,
                                "File could not be read",
                                f"{relative} was not readable as UTF-8: {error}.",
                                "Fix permissions or encoding so reproducibility checks can inspect this file.",
                                relative,
                            )
                        )
                files.append(
                    ProjectFile(
                        relative_path=relative,
                        absolute_path=str(path),
                        text=text,
                        unreadable=read_error is not None,
                        read_error=read_error,
                    )
                )
    except OSError as error:
        walk_error = error

    if walk_error is not None:
        error = walk_error
        findings.append(
            make_finding(
                "RP-INPUT-001",
                Severity.medium,
                "Project contents could not be fully enumerated",
                f"The target directory could not be enumerated: {error}",
                "Check filesystem permissions and run the analysis again.",
            )
        )
    files.sort(key=lambda item: item.relative_path.casefold())
    return tuple(files), findings, sorted(unreadable), tuple(sorted(directories))


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str | None, int | None, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.rule_id, finding.file_path, finding.line_number, finding.title)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return sorted(
        result,
        key=lambda item: (
            list(Severity).index(item.severity),
            item.rule_id,
            item.file_path or "",
            item.line_number or 0,
        ),
    )


def _summary(findings: list[Finding], score: int, project_type: str) -> str:
    critical = sum(item.severity is Severity.critical for item in findings)
    high = sum(item.severity is Severity.high for item in findings)
    if critical:
        return f"{project_type} scored {score}/100 with {critical} critical and {high} high-severity reproducibility finding(s)."
    if high:
        return f"{project_type} scored {score}/100 with {high} high-severity reproducibility finding(s); address them before sharing a clean clone."
    return f"{project_type} scored {score}/100; no critical or high-severity findings were detected."


def analyze(target: Path) -> AnalysisReport:
    """Analyze a project without writing to it."""

    if not target.exists():
        raise ValueError(f"Target path does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Target path is not a directory: {target}")
    root = target.resolve()
    files, input_findings, unreadable, directories = _inventory(root)
    if not files:
        raise ValueError(
            f"No project files were found in {root}. Choose a folder containing source code or a project manifest."
        )
    context = ScanContext(root=root, files=files, directories=directories)

    dependency_result = dependencies.detect(context)
    runtime_result = runtime.detect(context, dependency_result.languages)
    environment_result = environment.detect(context)
    container_result = containers.detect(context, bool(dependency_result.manifests or dependency_result.languages or files))
    test_result = tests.detect(context, dependency_result.languages)
    documentation_result = documentation.detect(context)
    git_result = git.detect(context)
    ml_result = machine_learning.detect(context)

    all_findings = (
        input_findings
        + dependency_result.findings
        + runtime_result.findings
        + environment_result.findings
        + container_result.findings
        + test_result.findings
        + paths.detect(context)
        + documentation_result.findings
        + git_result.findings
        + ml_result.findings
    )
    findings = with_default_deductions(_deduplicate(all_findings))
    score, reasons = calculate_score(findings)
    summary = _summary(findings, score, dependency_result.project_type)
    return AnalysisReport(
        target_path=str(root),
        project_type=dependency_result.project_type,
        languages=dependency_result.languages,
        dependency_manifests=dependency_result.manifests,
        dependency_lockfiles=dependency_result.lockfiles,
        runtime_files=runtime_result.runtime_files,
        environment_files=environment_result.environment_files,
        runtime_definitions=container_result.runtime_definitions,
        test_configuration=test_result.configuration,
        likely_test_commands=test_result.commands,
        git_repository=git_result.is_repository,
        environment_variables_used=environment_result.used,
        environment_variables_documented=environment_result.documented,
        unreadable_files=unreadable,
        findings=findings,
        score=score,
        score_reasons=reasons,
        summary=summary,
        ml_frameworks=ml_result.frameworks,
        model_artifacts=ml_result.model_artifacts,
        dataset_artifacts=ml_result.dataset_artifacts,
        ml_entrypoints=ml_result.entrypoints,
    )
