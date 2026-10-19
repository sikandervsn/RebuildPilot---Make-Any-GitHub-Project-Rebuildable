"""Detection of machine-specific absolute paths."""

from __future__ import annotations

import re

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
                findings.append(
                    make_finding(
                        "RP-PATH-001",
                        Severity.critical,
                        "Machine-specific absolute path detected",
                        "A user or machine-specific absolute path is embedded in project content and will not resolve consistently elsewhere.",
                        "Use a relative path, pathlib.Path, an environment variable, or a configurable project root.",
                        item.relative_path,
                        line_number,
                    )
                )
    return findings
