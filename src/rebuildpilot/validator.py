"""Safe, local validation of detected project test and container commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .models import AnalysisReport, CheckStatus, ValidationCheck, ValidationReport
from .scanner import IGNORED_DIRECTORIES, analyze


SUPPORTED_TEST_COMMANDS = {
    "python -m pytest",
    "pytest",
    "npm test",
    "make test",
    "go test ./...",
    "cargo test",
}
MAX_OUTPUT_LENGTH = 4_000


def _shorten_output(output: str) -> str:
    cleaned = output.strip()
    if len(cleaned) <= MAX_OUTPUT_LENGTH:
        return cleaned
    return cleaned[:MAX_OUTPUT_LENGTH] + "\n...[output truncated]"


def _run_command(command: str, cwd: Path, timeout: int) -> ValidationCheck:
    tokens = command.split()
    if command not in SUPPORTED_TEST_COMMANDS or not tokens:
        return ValidationCheck(
            name=f"test: {command}",
            status=CheckStatus.skipped,
            command=command,
            details="The detected command is not in RebuildPilot's safe validation allowlist.",
        )
    if shutil.which(tokens[0]) is None:
        return ValidationCheck(
            name=f"test: {command}",
            status=CheckStatus.skipped,
            command=command,
            details=f"The `{tokens[0]}` executable is not available on this machine.",
        )

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            tokens,
            cwd=cwd,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        duration = round(time.perf_counter() - started, 3)
        output = _shorten_output((error.stdout or "") + (error.stderr or ""))
        details = f"Command exceeded the {timeout}-second timeout."
        if output:
            details += f"\n{output}"
        return ValidationCheck(
            name=f"test: {command}",
            status=CheckStatus.failed,
            command=command,
            duration_seconds=duration,
            details=details,
        )
    except OSError as error:
        duration = round(time.perf_counter() - started, 3)
        return ValidationCheck(
            name=f"test: {command}",
            status=CheckStatus.failed,
            command=command,
            duration_seconds=duration,
            details=f"Could not execute the command: {error}",
        )

    duration = round(time.perf_counter() - started, 3)
    output = _shorten_output("\n".join(part for part in (completed.stdout, completed.stderr) if part))
    details = f"Command exited with code {completed.returncode}."
    if output:
        details += f"\n{output}"
    return ValidationCheck(
        name=f"test: {command}",
        status=CheckStatus.passed if completed.returncode == 0 else CheckStatus.failed,
        command=command,
        exit_code=completed.returncode,
        duration_seconds=duration,
        details=details,
    )


def _docker_check(project_root: Path, timeout: int) -> ValidationCheck:
    command = "docker build --pull=false --tag rebuildpilot-validation:local ."
    if not (project_root / "Dockerfile").is_file():
        return ValidationCheck(
            name="docker build",
            status=CheckStatus.skipped,
            command=command,
            details="No Dockerfile was detected; Docker build verification was skipped.",
        )
    if shutil.which("docker") is None:
        return ValidationCheck(
            name="docker build",
            status=CheckStatus.failed,
            command=command,
            details="Docker was requested, but the `docker` executable is not available on this machine.",
        )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            ["docker", "build", "--pull=false", "--tag", "rebuildpilot-validation:local", "."],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ValidationCheck(
            name="docker build",
            status=CheckStatus.failed,
            command=command,
            duration_seconds=round(time.perf_counter() - started, 3),
            details=f"Docker build exceeded the {timeout}-second timeout.",
        )
    except OSError as error:
        return ValidationCheck(
            name="docker build",
            status=CheckStatus.failed,
            command=command,
            duration_seconds=round(time.perf_counter() - started, 3),
            details=f"Could not execute Docker: {error}",
        )

    output = _shorten_output("\n".join(part for part in (completed.stdout, completed.stderr) if part))
    details = f"Docker build exited with code {completed.returncode}."
    if output:
        details += f"\n{output}"
    return ValidationCheck(
        name="docker build",
        status=CheckStatus.passed if completed.returncode == 0 else CheckStatus.failed,
        command=command,
        exit_code=completed.returncode,
        duration_seconds=round(time.perf_counter() - started, 3),
        details=details,
    )


def _analysis_check(report: AnalysisReport) -> ValidationCheck:
    critical = report.critical_findings()
    if critical:
        details = "Critical findings prevent a clean rebuild:\n" + "\n".join(
            f"- {finding.rule_id}: {finding.title}" for finding in critical
        )
        return ValidationCheck(name="static analysis", status=CheckStatus.failed, details=details)
    return ValidationCheck(
        name="static analysis",
        status=CheckStatus.passed,
        details="No critical reproducibility findings were detected.",
    )


def _sandbox_copy(root: Path, destination: Path) -> None:
    """Copy the target before executing tests so validation does not write to it."""

    ignored = shutil.ignore_patterns(*IGNORED_DIRECTORIES)
    shutil.copytree(root, destination, ignore=ignored, dirs_exist_ok=True)


def validate(target: Path, *, run_tests: bool = True, docker: bool = False, timeout: int = 120) -> ValidationReport:
    """Analyze a project, then run detected checks in a temporary copy."""

    if timeout < 1:
        raise ValueError("Validation timeout must be at least 1 second")
    analysis = analyze(target)
    checks = [_analysis_check(analysis)]

    with tempfile.TemporaryDirectory(prefix="rebuildpilot-validate-") as temporary:
        sandbox = Path(temporary) / "project"
        try:
            _sandbox_copy(Path(analysis.target_path), sandbox)
        except OSError as error:
            checks.append(
                ValidationCheck(
                    name="validation sandbox",
                    status=CheckStatus.failed,
                    details=f"Could not create a temporary validation copy: {error}",
                )
            )
        else:
            if run_tests:
                if not analysis.likely_test_commands:
                    checks.append(
                        ValidationCheck(
                            name="tests",
                            status=CheckStatus.failed,
                            details="No deterministic test command was detected.",
                        )
                    )
                else:
                    checks.extend(
                        _run_command(command, sandbox, timeout)
                        for command in analysis.likely_test_commands
                    )
            else:
                checks.append(
                    ValidationCheck(
                        name="tests",
                        status=CheckStatus.skipped,
                        details="Test execution was disabled with --skip-tests.",
                    )
                )
            if docker:
                checks.append(_docker_check(sandbox, timeout))

    passed = not any(check.status is CheckStatus.failed for check in checks)
    if passed:
        summary = "Validation passed: static checks and requested local commands completed without failures."
    else:
        failures = sum(check.status is CheckStatus.failed for check in checks)
        summary = f"Validation failed with {failures} failed check(s); review the details before sharing a clean clone."
    return ValidationReport(
        target_path=analysis.target_path,
        analysis=analysis,
        checks=checks,
        passed=passed,
        summary=summary,
    )
