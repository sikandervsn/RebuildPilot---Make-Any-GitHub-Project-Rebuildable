"""Runtime and language-version file detection."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


RUNTIME_NAMES = {
    ".python-version",
    ".nvmrc",
    ".node-version",
    ".tool-versions",
    "runtime.txt",
    "rust-toolchain",
    "rust-toolchain.toml",
}
VERSION_PATTERNS = (
    re.compile(r"^\s*requires-python\s*=\s*['\"]([^'\"]+)", re.MULTILINE),
    re.compile(r"^\s*python_requires\s*=\s*['\"]([^'\"]+)", re.MULTILINE),
    re.compile(r"^\s*go\s+([0-9.]+)", re.MULTILINE),
)


class RuntimeResult(BaseModel):
    runtime_files: list[str]
    findings: list[Finding]


def detect(context: ScanContext, languages: list[str]) -> RuntimeResult:
    runtime_files = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).name.lower() in {name.lower() for name in RUNTIME_NAMES}
        or Path(item.relative_path).name.lower() in {"go.mod", "pyproject.toml"}
        and item.text is not None
        and any(pattern.search(item.text) for pattern in VERSION_PATTERNS)
    )
    findings: list[Finding] = []
    if runtime_files:
        findings.append(
            make_finding(
                "RP-RUNTIME-002",
                Severity.info,
                "Runtime version declaration detected",
                f"Runtime evidence found in: {', '.join(runtime_files)}.",
                "Keep the declared runtime version aligned with CI and deployment images.",
            )
        )
    elif languages:
        findings.append(
            make_finding(
                "RP-RUNTIME-001",
                Severity.low,
                "Runtime version is not pinned",
                "Source files suggest a programming language, but no recognized runtime/version file was found.",
                "Add a runtime declaration such as .python-version, .nvmrc, go.mod, or rust-toolchain.toml.",
            )
        )
    return RuntimeResult(runtime_files=runtime_files, findings=findings)
