"""Environment-variable usage and .env.example comparison."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


ENV_PATTERNS = (
    re.compile(r"\b(?:os\.environ(?:\.get)?|os\.getenv)\s*(?:\[|\()\s*['\"]([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bprocess\.env(?:\[['\"]|\.)([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bSystem\.getenv\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}|\$([A-Z][A-Z0-9_]*)"),
    re.compile(r"^\s*ENV\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
)
ENV_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)


class EnvironmentResult(BaseModel):
    environment_files: list[str]
    used: list[str]
    documented: list[str]
    findings: list[Finding]


def _used_variables(text: str) -> set[str]:
    values: set[str] = set()
    for pattern in ENV_PATTERNS:
        for match in pattern.finditer(text):
            values.update(group for group in match.groups() if group)
    return values


def detect(context: ScanContext) -> EnvironmentResult:
    env_files = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).name.lower() in {".env", ".env.example", ".env.template", ".env.sample"}
    )
    used: set[str] = set()
    for item in context.text_files():
        if Path(item.relative_path).name.lower() in {".env", ".env.example", ".env.template", ".env.sample"}:
            continue
        used.update(_used_variables(item.text or ""))

    example_files = [
        item for item in context.files if Path(item.relative_path).name.lower() in {".env.example", ".env.template", ".env.sample"}
    ]
    documented: set[str] = set()
    for item in example_files:
        documented.update(ENV_ASSIGNMENT.findall(item.text or ""))

    findings: list[Finding] = []
    if used and not example_files:
        findings.append(
            make_finding(
                "RP-ENV-001",
                Severity.high,
                "Environment variables are undocumented",
                f"The project uses: {', '.join(sorted(used))}, but has no .env.example or equivalent template.",
                "Commit a non-secret .env.example that lists every required variable and describes safe placeholder values.",
            )
        )
    missing = sorted(used - documented)
    if missing and example_files:
        example_path = example_files[0].relative_path
        findings.append(
            make_finding(
                "RP-ENV-002",
                Severity.medium,
                "Environment template is incomplete",
                f"Variables used in source but absent from {example_path}: {', '.join(missing)}.",
                "Add each required variable to the template without committing real credentials.",
                example_path,
            )
        )
    if example_files and not missing:
        findings.append(
            make_finding(
                "RP-ENV-003",
                Severity.info,
                "Environment template covers detected variables",
                f"Detected variables are represented in {example_files[0].relative_path}.",
                "Review the template whenever configuration variables change.",
                example_files[0].relative_path,
            )
        )
    return EnvironmentResult(
        environment_files=env_files,
        used=sorted(used),
        documented=sorted(documented),
        findings=findings,
    )
