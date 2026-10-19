"""README setup and test instruction checks."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


README_NAMES = {"readme", "readme.md", "readme.rst", "readme.txt"}


class DocumentationResult(BaseModel):
    readme_path: str | None
    findings: list[Finding]


def detect(context: ScanContext) -> DocumentationResult:
    readme = next(
        (item for item in context.files if Path(item.relative_path).name.lower() in README_NAMES),
        None,
    )
    findings: list[Finding] = []
    if readme is None:
        findings.append(
            make_finding(
                "RP-DOC-001",
                Severity.medium,
                "README setup instructions are missing",
                "No README file was found in the project root.",
                "Add setup, usage, test, and environment instructions for a clean clone.",
            )
        )
    else:
        content = (readme.text or "").lower()
        missing = []
        if not re.search(r"\b(?:install|setup|get(?:ting)? started)\b", content):
            missing.append("setup or installation")
        if not re.search(r"\b(?:test|pytest|npm test|make test)\b", content):
            missing.append("test command")
        if missing:
            findings.append(
                make_finding(
                    "RP-DOC-002",
                    Severity.medium,
                    "README instructions are incomplete",
                    f"{readme.relative_path} does not clearly document: {', '.join(missing)}.",
                    "Document exact install/setup commands and the command that validates the project.",
                    readme.relative_path,
                )
            )
        else:
            findings.append(
                make_finding(
                    "RP-DOC-003",
                    Severity.info,
                    "README contains setup and test instructions",
                    f"{readme.relative_path} includes recognizable setup and test guidance.",
                    "Keep documentation synchronized with the actual commands and lockfiles.",
                    readme.relative_path,
                )
            )
    return DocumentationResult(readme_path=readme.relative_path if readme else None, findings=findings)
