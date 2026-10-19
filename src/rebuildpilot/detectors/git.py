"""Git repository detection."""

from __future__ import annotations

from pydantic import BaseModel

from ..models import Finding, Severity
from .common import make_finding
from .context import ScanContext


class GitResult(BaseModel):
    is_repository: bool
    findings: list[Finding]


def detect(context: ScanContext) -> GitResult:
    git_marker = context.root / ".git"
    is_repository = git_marker.is_dir() or git_marker.is_file()
    if is_repository:
        findings = [
            make_finding(
                "RP-GIT-002",
                Severity.info,
                "Git repository detected",
                "The target contains a .git directory or worktree marker.",
                "Commit manifests, lockfiles, runtime declarations, tests, and documentation together.",
                ".git",
            )
        ]
    else:
        findings = [
            make_finding(
                "RP-GIT-001",
                Severity.medium,
                "Target is not a Git repository",
                "No .git directory or worktree marker was found at the target root.",
                "Run the analysis from a cloned Git repository or include the target in version control before sharing it.",
            )
        ]
    return GitResult(is_repository=is_repository, findings=findings)
