"""Container and other reproducible runtime definition detection."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


RUNTIME_DEFINITION_NAMES = {
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "flake.nix",
    "devcontainer.json",
}


class ContainerResult(BaseModel):
    runtime_definitions: list[str]
    findings: list[Finding]


def detect(context: ScanContext, has_project_content: bool) -> ContainerResult:
    definitions = sorted(
        item.relative_path
        for item in context.files
        if Path(item.relative_path).name.lower() in RUNTIME_DEFINITION_NAMES
    )
    if definitions:
        findings = [
            make_finding(
                "RP-CONTAINER-002",
                Severity.info,
                "Reproducible runtime definition detected",
                f"Runtime definition(s): {', '.join(definitions)}.",
                "Keep the runtime definition pinned and verify it in CI.",
                definitions[0],
            )
        ]
    elif has_project_content:
        findings = [
            make_finding(
                "RP-CONTAINER-001",
                Severity.medium,
                "No reproducible runtime definition detected",
                "The project has source or dependency files but no Dockerfile, compose file, devcontainer, or Nix flake.",
                "Add a Dockerfile or another documented runtime definition when a clean-machine environment matters.",
            )
        ]
    else:
        findings = []
    return ContainerResult(runtime_definitions=definitions, findings=findings)
