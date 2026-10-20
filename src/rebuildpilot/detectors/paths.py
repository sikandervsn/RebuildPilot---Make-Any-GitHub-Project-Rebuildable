"""Detection of machine-specific absolute paths."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


WINDOWS_ABSOLUTE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/][^\r\n\"']+)")
UNIX_HOME_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^\s\"']+")


def detect(context: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    for item in context.text_files():
        for line_number, line in enumerate((item.text or "").splitlines(), start=1):
            if WINDOWS_ABSOLUTE.search(line) or UNIX_HOME_ABSOLUTE.search(line):
                parts = {part.casefold() for part in Path(item.relative_path).parts}
                is_non_runtime_content = bool(
                    parts.intersection({"test", "tests", "fixture", "fixtures", "example", "examples", "docs", "doc"})
                )
                severity = Severity.medium if is_non_runtime_content else Severity.critical
                scope = "test, fixture, documentation, or example content" if is_non_runtime_content else "runtime or project content"
                findings.append(
                    make_finding(
                        "RP-PATH-001",
                        severity,
                        "Machine-specific absolute path detected",
                        f"A user or machine-specific absolute path is embedded in {scope}.",
                        "Use a relative path, pathlib.Path, an environment variable, or a configurable project root.",
                        item.relative_path,
                        line_number,
                    )
                )
    return findings
