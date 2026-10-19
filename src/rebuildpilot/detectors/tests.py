"""Test configuration and likely command detection."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


TEST_CONFIG_NAMES = {"pytest.ini", "tox.ini", "noxfile.py", "jest.config.js", "vitest.config.ts", "Makefile"}
TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.spec\.[jt]sx?|[^/]+\.test\.[jt]sx?)$", re.IGNORECASE)


class TestResult(BaseModel):
    configuration: list[str]
    commands: list[str]
    findings: list[Finding]


def _package_test_command(item_text: str) -> bool:
    try:
        data = json.loads(item_text)
    except json.JSONDecodeError:
        return False
    return isinstance(data.get("scripts"), dict) and bool(data["scripts"].get("test"))


def detect(context: ScanContext, languages: list[str]) -> TestResult:
    configuration: list[str] = []
    commands: list[str] = []
    names = {Path(item.relative_path).name.lower(): item for item in context.files}
    for item in context.files:
        basename = Path(item.relative_path).name
        if basename.lower() in TEST_CONFIG_NAMES:
            configuration.append(item.relative_path)
        if TEST_FILE_RE.search(item.relative_path.replace("\\", "/")):
            configuration.append(item.relative_path)
        if basename.lower() == "pyproject.toml" and item.text and "pytest" in item.text.lower():
            configuration.append(item.relative_path)
        if basename.lower() == "package.json" and item.text and _package_test_command(item.text):
            configuration.append(item.relative_path)

    if "Python" in languages and configuration:
        commands.append("python -m pytest")
    package = names.get("package.json")
    if package and package.text and _package_test_command(package.text):
        commands.append("npm test")
    makefile = names.get("makefile")
    if makefile and makefile.text and re.search(r"^test\s*:", makefile.text, re.MULTILINE):
        commands.append("make test")
    if "Go" in languages:
        commands.append("go test ./...")
    if "Rust" in languages:
        commands.append("cargo test")
    configuration = sorted(set(configuration))
    commands = list(dict.fromkeys(commands))

    if commands:
        findings = [
            make_finding(
                "RP-TEST-002",
                Severity.info,
                "Test command detected",
                f"Likely test command(s): {', '.join(commands)}.",
                "Run the command in CI and document it for contributors.",
            )
        ]
    else:
        findings = [
            make_finding(
                "RP-TEST-001",
                Severity.medium,
                "No test command detected",
                "No recognizable test configuration, test files, or package test script was found.",
                "Add a deterministic test command and run it in continuous integration.",
            )
        ]
    return TestResult(configuration=configuration, commands=commands, findings=findings)
