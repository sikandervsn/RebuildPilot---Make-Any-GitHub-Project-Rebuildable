"""Bounded, deterministic metadata repairs for an analyzed project.

The public :func:`repair` function is deliberately planning-first.  It uses
the scanner's findings to identify two safe mutations only:

* create or append missing variable names in a non-secret environment template; and
* create ``.python-version`` when metadata contains one exact Python version.

Everything else remains a skipped finding. No source code, dependency lockfiles,
Git metadata, or documentation is ever created or rewritten here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AnalysisReport, Finding
from .scanner import analyze


_ENV_TEMPLATE_NAMES = {".env.example", ".env.template", ".env.sample"}
_PYTHON_METADATA_NAMES = {"pyproject.toml", "setup.py", "setup.cfg"}
_DECLARATION = re.compile(
    r"(?:[\"']?requires-python[\"']?|python_requires)\s*=\s*([\"'])([^\"']+)\1",
    re.IGNORECASE,
)
_UNQUOTED_SETUP_CFG_DECLARATION = re.compile(
    r"(?:[\"']?requires-python[\"']?|python_requires)\s*=\s*(?![\"'])([^#;]+?)\s*(?:[#;].*)?$",
    re.IGNORECASE,
)
_EXACT_VERSION = re.compile(r"^(?:==\s*)?([0-9]+)\.([0-9]+)(?:\.[0-9]+(?:\.[0-9]+)*)?$")


class _UnsafePath(ValueError):
    """An input or discovered path cannot be safely kept inside the target."""


@dataclass(frozen=True)
class _PlannedChange:
    relative_path: str
    kind: str
    expected_bytes: bytes
    new_bytes: bytes
    description: str
    rule_ids: tuple[str, ...]


def _validated_root(target: str | Path) -> Path:
    candidate = Path(target).expanduser()
    if not candidate.exists():
        raise ValueError(f"Target path does not exist: {target}")
    if not candidate.is_dir():
        raise ValueError(f"Target path is not a directory: {target}")
    return candidate.resolve()


def _safe_path(root: Path, relative_path: str) -> Path:
    """Return a path only when its resolved location is under ``root``."""

    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise _UnsafePath(f"Path is not a safe relative path: {relative_path}")
    candidate = root.joinpath(relative)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise _UnsafePath(f"Path is outside the target root: {relative_path}") from error
    return candidate


def _read_utf8(path: Path) -> str:
    # newline="" is important: universal-newline translation would hide the
    # original style that the environment repair must preserve.
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _newline_style(text: str) -> str:
    match = re.search(r"\r\n|\r|\n", text)
    return match.group(0) if match else "\n"


def _append_environment_variables(text: str, names: list[str]) -> str:
    newline = _newline_style(text)
    additions = "".join(f"{name}={newline}" for name in names)
    if not additions:
        return text
    if not text or text.endswith(("\n", "\r")):
        return text + additions
    return text + newline + additions


def _metadata_declarations(root: Path, report: AnalysisReport) -> tuple[list[str], str | None]:
    declarations: list[str] = []
    for relative in report.dependency_manifests:
        if Path(relative).name.lower() not in _PYTHON_METADATA_NAMES:
            continue
        try:
            path = _safe_path(root, relative)
            if not path.exists() or not path.is_file():
                return [], f"Python metadata file is not a regular file: {relative}."
            text = _read_utf8(path)
        except (OSError, UnicodeError, _UnsafePath) as error:
            return [], f"Python version metadata could not be read safely: {error}."

        # A malformed pyproject is not reliable metadata, even if a regular
        # expression happens to find a version-looking string in it.
        if Path(relative).name.lower() == "pyproject.toml":
            try:
                import tomllib

                tomllib.loads(text)
            except (ValueError, tomllib.TOMLDecodeError) as error:
                return [], f"pyproject.toml is not valid TOML: {error}."

        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            declarations.extend(match.group(2).strip() for match in _DECLARATION.finditer(line))
            if Path(relative).name.lower() == "setup.cfg":
                declarations.extend(match.group(1).strip() for match in _UNQUOTED_SETUP_CFG_DECLARATION.finditer(line))
    return declarations, None


def _reduce_exact_python_version(value: str) -> str | None:
    value = value.strip()
    # A single == specifier or a bare numeric version is exact.  Ranges,
    # wildcards, prereleases, and comma-separated specifiers are unresolved.
    if value.startswith("=="):
        value = value[2:].strip()
    elif value[:1] in {"<", ">", "!", "~", "="} or "," in value:
        return None
    match = _EXACT_VERSION.fullmatch(value)
    if not match:
        return None
    return f"{int(match.group(1))}.{int(match.group(2))}"


def _exact_python_version(root: Path, report: AnalysisReport) -> tuple[str | None, str]:
    declarations, read_error = _metadata_declarations(root, report)
    if read_error:
        return None, read_error
    if not declarations:
        return None, "No requires-python or python_requires declaration was found."

    reduced = [_reduce_exact_python_version(value) for value in declarations]
    if any(value is None for value in reduced):
        return None, "The Python requirement is a range or otherwise cannot be reduced to one major.minor."
    versions = {value for value in reduced if value is not None}
    if len(versions) != 1:
        return None, "Python metadata contains conflicting exact versions."
    return next(iter(versions)), ""


def _skipped(
    rule_id: str,
    reason: str,
    *,
    title: str = "Repair skipped",
    file_path: str | None = None,
    severity: str = "info",
) -> dict[str, str | None]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "title": title,
        "file_path": file_path,
        "reason": reason,
    }


def _finding_skipped(finding: Finding, reason: str) -> dict[str, str | None]:
    return _skipped(
        finding.rule_id,
        reason,
        title=finding.title,
        file_path=finding.file_path,
        severity=finding.severity.value,
    )


def _plan_changes(
    root: Path, report: AnalysisReport
) -> tuple[list[_PlannedChange], dict[str, str], list[dict[str, str | None]]]:
    changes: list[_PlannedChange] = []
    failure_reasons: dict[str, str] = {}
    synthetic_skips: list[dict[str, str | None]] = []

    missing_variables = sorted(
        set(report.environment_variables_used) - set(report.environment_variables_documented)
    )
    if missing_variables:
        template_relatives = sorted(
            relative
            for relative in report.environment_files
            if Path(relative).name.lower() in _ENV_TEMPLATE_NAMES
        )
        if not template_relatives:
            relative = ".env.example"
            try:
                path = _safe_path(root, relative)
            except _UnsafePath as error:
                failure_reasons["RP-ENV-001"] = f"Environment template path is unsafe: {error}."
            else:
                if path.exists() or path.is_symlink():
                    failure_reasons["RP-ENV-001"] = (
                        "An environment template path exists but is not a regular readable template."
                    )
                else:
                    changes.append(
                        _PlannedChange(
                            relative_path=relative,
                            kind="environment_template",
                            expected_bytes=b"",
                            new_bytes=_append_environment_variables("", missing_variables).encode("utf-8"),
                            description=(
                                f"Create a non-secret environment template with "
                                f"{len(missing_variables)} required variable name(s)."
                            ),
                            rule_ids=("RP-ENV-001",),
                        )
                    )
        else:
            selected = False
            last_error = "No safe environment template could be selected."
            for relative in template_relatives:
                try:
                    path = _safe_path(root, relative)
                    if not path.exists() or not path.is_file():
                        raise OSError(f"not a regular file: {relative}")
                    original = _read_utf8(path)
                except (OSError, UnicodeError, _UnsafePath) as error:
                    last_error = f"Environment template was not readable safely: {error}."
                    continue
                updated = _append_environment_variables(original, missing_variables)
                if updated == original:
                    continue
                changes.append(
                    _PlannedChange(
                        relative_path=relative,
                        kind="environment_template",
                        expected_bytes=original.encode("utf-8"),
                        new_bytes=updated.encode("utf-8"),
                        description=f"Append {len(missing_variables)} missing environment variable name(s).",
                        rule_ids=("RP-ENV-002",),
                    )
                )
                selected = True
                break
            if not selected:
                failure_reasons["RP-ENV-002"] = last_error

    python_relevant = "Python" in report.languages or any(
        Path(relative).name.lower() in _PYTHON_METADATA_NAMES for relative in report.dependency_manifests
    )
    if python_relevant:
        version, version_reason = _exact_python_version(root, report)
        python_version_missing = False
        python_version_present = False
        try:
            python_version_path = _safe_path(root, ".python-version")
        except _UnsafePath as error:
            version = None
            version_reason = f".python-version is not safely contained by the target root: {error}."
            failure_reasons["RP-RUNTIME-001"] = version_reason
        else:
            if python_version_path.exists() or python_version_path.is_symlink():
                if python_version_path.is_file():
                    version = None
                    python_version_present = True
                else:
                    version = None
                    version_reason = ".python-version already exists but is not a regular file."
                    failure_reasons["RP-RUNTIME-001"] = version_reason
            elif version is not None:
                python_version_missing = True
                changes.append(
                    _PlannedChange(
                        relative_path=".python-version",
                        kind="python_version",
                        expected_bytes=b"",
                        new_bytes=f"{version}\n".encode("utf-8"),
                        description="Create .python-version from one exact Python major.minor.",
                        rule_ids=("RP-RUNTIME-001",),
                    )
                )

        if version is None and not python_version_missing and not python_version_present:
            # Keep unresolved version evidence visible even when the scanner
            # did not emit RP-RUNTIME-001 (for example, a valid pyproject
            # whose only runtime signal is its metadata).
            failure_reasons.setdefault("RP-RUNTIME-001", version_reason)
            if not any(finding.rule_id == "RP-RUNTIME-001" for finding in report.findings):
                synthetic_skips.append(
                    _skipped(
                        "RP-RUNTIME-001",
                        version_reason,
                        title="Exact Python version pin unresolved",
                        file_path=".python-version",
                        severity="medium",
                    )
                )

    changes.sort(key=lambda change: change.relative_path)
    return changes, failure_reasons, synthetic_skips


def _apply_change(root: Path, change: _PlannedChange, use_backup: bool) -> tuple[str, str | None, str | None]:
    """Apply one change, returning status, reason, and optional backup path."""

    try:
        destination = _safe_path(root, change.relative_path)
    except _UnsafePath as error:
        return "skipped", str(error), None

    try:
        destination_exists = destination.exists() or destination.is_symlink()
        if destination_exists:
            if not destination.is_file():
                return "skipped", "The destination is not a regular file.", None
            current = destination.read_bytes()
        else:
            current = b""
    except OSError as error:
        return "skipped", f"The destination could not be read: {error}.", None

    if current != change.expected_bytes:
        return "skipped", "The destination changed after planning; no overwrite was attempted.", None
    if current == change.new_bytes:
        return "unchanged", None, None

    backup_relative: str | None = None
    if use_backup and destination_exists:
        backup_relative = f"{change.relative_path}.rebuildpilot.bak"
        try:
            backup = _safe_path(root, backup_relative)
            if backup.exists() or backup.is_symlink():
                return "skipped", f"Backup already exists and was not overwritten: {backup_relative}.", None
            with backup.open("xb") as stream:
                stream.write(current)
        except (OSError, _UnsafePath) as error:
            return "skipped", f"Could not create the backup before mutation: {error}.", None

    try:
        with destination.open("wb") as stream:
            stream.write(change.new_bytes)
    except OSError as error:
        return "skipped", f"Could not write the repaired file: {error}.", None
    return "changed", None, backup_relative


def _complete_skips(
    report: AnalysisReport,
    handled_rules: set[str],
    failure_reasons: dict[str, str],
    synthetic_skips: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    skipped = list(synthetic_skips)
    report_rule_ids = {finding.rule_id for finding in report.findings}
    for finding in report.findings:
        if finding.rule_id in handled_rules:
            continue
        reason = failure_reasons.get(
            finding.rule_id,
            "This finding is outside the bounded repair scope; no source, lockfile, Git, or README mutation is supported.",
        )
        skipped.append(_finding_skipped(finding, reason))

    for rule_id, reason in failure_reasons.items():
        if rule_id not in report_rule_ids:
            skipped.append(_skipped(rule_id, reason, file_path=".python-version" if rule_id == "RP-RUNTIME-001" else None))

    unique: dict[tuple[str, str | None], dict[str, str | None]] = {}
    for item in skipped:
        key = (str(item["rule_id"]), item.get("file_path"))
        unique.setdefault(key, item)
    return [unique[key] for key in sorted(unique)]


def repair(target: str | Path, *, apply: bool = False, backup: bool = False) -> dict[str, Any]:
    """Plan or apply bounded deterministic metadata repairs.

    ``apply=False`` is the safe default and never writes to ``target``.
    When ``apply=True``, only the bounded repair kinds documented in this module
    can mutate files. The returned dictionary contains only JSON-serializable
    values so a future CLI can render it directly.
    """

    root = _validated_root(target)
    before = analyze(root)
    changes, failure_reasons, synthetic_skips = _plan_changes(root, before)

    changed_files: list[str] = []
    backups: list[str] = []
    change_details: list[dict[str, str | None]] = []
    handled_rules: set[str] = set()

    if not apply:
        handled_rules.update(rule_id for change in changes for rule_id in change.rule_ids)
    else:
        for change in changes:
            status, reason, backup_relative = _apply_change(root, change, backup)
            if status in {"changed", "unchanged"}:
                handled_rules.update(change.rule_ids)
            if status == "changed":
                changed_files.append(change.relative_path)
                if backup_relative is not None:
                    backups.append(backup_relative)
                change_details.append(
                    {
                        "path": change.relative_path,
                        "kind": change.kind,
                        "backup_path": backup_relative,
                    }
                )
            elif status == "skipped" and reason is not None:
                for rule_id in change.rule_ids:
                    failure_reasons[rule_id] = reason

    if apply:
        after = analyze(root)
        after_score = after.score
    else:
        after_score = before.score

    skipped = _complete_skips(before, handled_rules, failure_reasons, synthetic_skips)
    planned_changes = [
        {
            "path": change.relative_path,
            "kind": change.kind,
            "description": change.description,
        }
        for change in changes
    ]
    summary = (
        f"Repair {'applied' if apply else 'planned'}: {len(changed_files) if apply else len(planned_changes)} "
        f"change(s); score {before.score}/100"
    )
    if apply:
        summary += f" -> {after_score}/100"
    return {
        "target_path": str(root),
        "apply_requested": apply,
        "backup_requested": backup,
        "planned_changes": planned_changes,
        "changed_files": sorted(changed_files),
        "backups": sorted(backups),
        "change_details": sorted(change_details, key=lambda item: str(item["path"])),
        "skipped_findings": skipped,
        "before_score": before.score,
        "after_score": after_score,
        "scores": {"before": before.score, "after": after_score},
        "summary": summary,
    }


def plan_repairs(target: str | Path) -> dict[str, Any]:
    """Convenience alias for an explicit non-mutating repair plan."""

    return repair(target, apply=False)


__all__ = ["plan_repairs", "repair"]
