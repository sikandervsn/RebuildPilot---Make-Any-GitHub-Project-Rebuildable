"""Safe repository onboarding and explicit GitHub publishing helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .models import AnalysisReport
from .rebuild import RebuildResult, rebuild
from .repair import repair
from .scanner import analyze


_GITHUB_URL = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+(?:\.git)?/?$")
_SSH_URL = re.compile(r"^git@github\.com:[^/\s]+/[^/\s]+(?:\.git)?$")
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_MAX_OUTPUT = 4000


@dataclass(frozen=True)
class RepositoryWorkspace:
    """A cloned repository and its safe, isolated workspace."""

    source: str
    root: Path
    branch: str
    temporary: bool

    def cleanup(self) -> None:
        if self.temporary:
            shutil.rmtree(self.root.parent, ignore_errors=True)


@dataclass(frozen=True)
class OnboardResult:
    """Result of cloning, analyzing, repairing, and rebuilding a repository."""

    workspace: RepositoryWorkspace
    analysis_before: AnalysisReport
    repair_result: dict[str, object]
    rebuild_result: RebuildResult
    analysis_after: AnalysisReport

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.workspace.source,
            "root": str(self.workspace.root),
            "branch": self.workspace.branch,
            "analysis_before": self.analysis_before.as_json_dict(),
            "repair": self.repair_result,
            "rebuild": self.rebuild_result.as_json_dict(),
            "analysis_after": self.analysis_after.as_json_dict(),
        }


def validate_repository_url(source: str) -> str:
    """Accept only GitHub HTTPS or SSH clone URLs."""

    value = source.strip()
    if not (_GITHUB_URL.fullmatch(value) or _SSH_URL.fullmatch(value)):
        raise ValueError("Repository URL must be a GitHub HTTPS URL or git@github.com SSH URL.")
    return value.rstrip("/")


def _run_git(args: tuple[str, ...], cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"Git command could not complete: {error}") from error
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode:
        raise ValueError(f"Git command failed ({completed.returncode}): {output[-_MAX_OUTPUT:]}")
    return output


def _branch_name(value: str) -> str:
    branch = value.strip()
    if not _BRANCH_NAME.fullmatch(branch) or branch.startswith(("/", ".")) or ".." in branch:
        raise ValueError("Branch name contains unsupported characters.")
    return branch


def clone_repository(source: str, destination: Path | None = None, *, branch: str | None = None) -> RepositoryWorkspace:
    """Clone a GitHub repository into a disposable directory."""

    source = validate_repository_url(source)
    root_parent = Path(destination).expanduser().resolve() if destination else Path(tempfile.mkdtemp(prefix="rebuildpilot-repo-"))
    if destination:
        root_parent.mkdir(parents=True, exist_ok=False)
    clone_root = root_parent / "project"
    args = ("clone", "--", source, str(clone_root))
    _run_git(args)
    selected_branch = branch.strip() if branch else _run_git(("branch", "--show-current"), cwd=clone_root).strip()
    if branch:
        selected_branch = _branch_name(branch)
        _run_git(("switch", "--track", f"origin/{selected_branch}"), cwd=clone_root)
    return RepositoryWorkspace(source=source, root=clone_root, branch=selected_branch, temporary=True)


def onboard_repository(source: str, *, branch: str | None = None, timeout: int = 120) -> OnboardResult:
    """Clone a repository, apply safe fixes in a branch, and verify a rebuild."""

    workspace = clone_repository(source, branch=branch)
    try:
        repair_branch = "rebuildpilot/fix-reproducibility"
        _run_git(("switch", "-c", repair_branch), cwd=workspace.root)
        workspace = RepositoryWorkspace(workspace.source, workspace.root, repair_branch, workspace.temporary)
        before = analyze(workspace.root)
        repair_result = repair(workspace.root, apply=True, backup=True)
        rebuild_result = rebuild(workspace.root, timeout=timeout)
        after = analyze(workspace.root)
        return OnboardResult(workspace, before, repair_result, rebuild_result, after)
    except Exception:
        workspace.cleanup()
        raise


def diff_repository(root: Path) -> str:
    """Return the reviewable diff produced in the current repository."""

    return _run_git(("diff", "--", "."), cwd=root)


def repository_has_changes(root: Path) -> bool:
    """Return whether tracked or untracked changes need to be published."""

    return bool(_run_git(("status", "--porcelain"), cwd=root).strip())


def commit_repository(root: Path, message: str) -> str:
    """Commit current changes after requiring a non-empty message."""

    message = message.strip()
    if not message:
        raise ValueError("Commit message cannot be empty.")
    _run_git(("add", "-A"), cwd=root)
    _run_git(("commit", "-m", message), cwd=root)
    return _run_git(("rev-parse", "HEAD"), cwd=root).strip()


def publish_repository(
    root: Path,
    *,
    remote: str = "origin",
    create_pr: bool = False,
    new_repository: str | None = None,
    private: bool = True,
) -> str:
    """Push to an existing remote or create a new GitHub repository with ``gh``."""

    if new_repository:
        if shutil.which("gh") is None:
            raise ValueError("GitHub CLI (`gh`) is required to create a repository.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", new_repository):
            raise ValueError("New repository name contains unsupported characters.")
        visibility = "--private" if private else "--public"
        args = ["repo", "create", new_repository, visibility, "--source", str(root), "--remote", remote, "--push"]
        try:
            completed = subprocess.run(
                ["gh", *args],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"GitHub CLI could not complete: {error}") from error
        if completed.returncode:
            details = (completed.stdout + "\n" + completed.stderr).strip()
            raise ValueError(f"GitHub repository creation failed: {details[-_MAX_OUTPUT:]}")
        return completed.stdout.strip() or f"Created and pushed new repository {new_repository}."
    _run_git(("push", "--set-upstream", remote, "HEAD"), cwd=root)
    if not create_pr:
        return "Changes pushed successfully."
    if shutil.which("gh") is None:
        raise ValueError("GitHub CLI (`gh`) is required to create a pull request.")
    try:
        completed = subprocess.run(
            ["gh", "pr", "create", "--fill", "--head", _run_git(("branch", "--show-current"), cwd=root).strip()],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"GitHub CLI could not complete: {error}") from error
    if completed.returncode:
        details = (completed.stdout + "\n" + completed.stderr).strip()
        raise ValueError(f"Pull request creation failed: {details[-_MAX_OUTPUT:]}")
    return completed.stdout.strip() or "Changes pushed and pull request created."


__all__ = [
    "OnboardResult",
    "RepositoryWorkspace",
    "clone_repository",
    "commit_repository",
    "diff_repository",
    "onboard_repository",
    "publish_repository",
    "repository_has_changes",
    "validate_repository_url",
]
