"""Run a deterministic dependency setup and test pass in a disposable copy.

The public :func:`rebuild` function deliberately has no command-string input.
Every command is derived from a recognized manifest or from the scanner's
detected test commands, and every subprocess runs with the temporary copy as
its working directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .models import AnalysisReport, CheckStatus
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


@dataclass(frozen=True)
class SetupPlan:
    """One allowlisted dependency setup command inferred from a manifest."""

    name: str
    command: str
    executable: str
    arguments: tuple[str, ...]

    @property
    def argv(self) -> tuple[str, ...]:
        return (self.executable, *self.arguments)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": self.command,
            "executable": self.executable,
            "arguments": list(self.arguments),
        }


@dataclass(frozen=True)
class RebuildStep:
    """Serializable outcome for static analysis, setup, or test execution."""

    name: str
    status: CheckStatus
    command: str | None = None
    exit_code: int | None = None
    duration_seconds: float | None = None
    details: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "details": self.details,
        }


@dataclass(frozen=True)
class RebuildResult:
    """Complete serializable result of an isolated clean-rebuild attempt."""

    target_path: str
    analysis: AnalysisReport
    static_analysis: RebuildStep
    setup_plan: tuple[SetupPlan, ...]
    setup: tuple[RebuildStep, ...]
    tests: tuple[RebuildStep, ...]
    passed: bool
    summary: str

    @property
    def checks(self) -> tuple[RebuildStep, ...]:
        """Return all checks in the order in which they are reported."""

        return (self.static_analysis, *self.setup, *self.tests)

    @property
    def setup_checks(self) -> tuple[RebuildStep, ...]:
        return self.setup

    @property
    def test_checks(self) -> tuple[RebuildStep, ...]:
        return self.tests

    def as_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "analysis": self.analysis.as_json_dict(),
            "static_analysis": self.static_analysis.as_dict(),
            "setup_plan": [plan.as_dict() for plan in self.setup_plan],
            "setup": [step.as_dict() for step in self.setup],
            "tests": [step.as_dict() for step in self.tests],
            "checks": [step.as_dict() for step in self.checks],
            "passed": self.passed,
            "summary": self.summary,
        }

    def as_json_dict(self) -> dict[str, object]:
        """Match the serialization naming used by the existing report models."""

        return self.as_dict()


def _command_text(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def _shorten_output(output: str) -> str:
    cleaned = output.strip()
    if len(cleaned) <= MAX_OUTPUT_LENGTH:
        return cleaned
    return cleaned[:MAX_OUTPUT_LENGTH] + "\n...[output truncated]"


def _output_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _combined_output(stdout: object, stderr: object) -> str:
    return _shorten_output("\n".join(part for part in (_output_text(stdout), _output_text(stderr)) if part))


def _find_root_file(root: Path, filename: str) -> Path | None:
    wanted = filename.casefold()
    try:
        matches = sorted(
            (path for path in root.iterdir() if path.is_file() and path.name.casefold() == wanted),
            key=lambda path: path.name,
        )
    except OSError:
        return None
    return matches[0] if matches else None


def _make_setup_plan(name: str, argv: tuple[str, ...]) -> SetupPlan:
    return SetupPlan(
        name=name,
        command=_command_text(argv),
        executable=argv[0],
        arguments=argv[1:],
    )


def build_setup_plan(target: Path) -> tuple[SetupPlan, ...]:
    """Build the fixed dependency setup plan for ``target``.

    Python uses ``requirements.lock`` in preference to ``requirements.txt``.
    If neither exists, a Python ``pyproject.toml`` is installed as a package.
    The other supported ecosystems use their package manager's deterministic
    manifest operation listed in the module contract.
    """

    root = Path(target).resolve()
    if not root.exists():
        raise ValueError(f"Target path does not exist: {target}")
    if not root.is_dir():
        raise ValueError(f"Target path is not a directory: {target}")

    plans: list[SetupPlan] = []
    requirements_lock = _find_root_file(root, "requirements.lock")
    requirements_txt = _find_root_file(root, "requirements.txt")
    pyproject = _find_root_file(root, "pyproject.toml")
    if requirements_lock or requirements_txt:
        requirements = requirements_lock or requirements_txt
        assert requirements is not None
        requirements_name = requirements.relative_to(root).as_posix()
        plans.append(
            _make_setup_plan(
                "python dependencies",
                (
                    "python",
                    "-m",
                    "pip",
                    "install",
                    "--no-input",
                    "--disable-pip-version-check",
                    "-r",
                    requirements_name,
                ),
            )
        )
    elif pyproject:
        plans.append(
            _make_setup_plan(
                "python package",
                ("python", "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "."),
            )
        )

    package_json = _find_root_file(root, "package.json")
    if package_json:
        npm_command = "ci" if _find_root_file(root, "package-lock.json") else "install"
        plans.append(_make_setup_plan("node dependencies", ("npm", npm_command)))

    if _find_root_file(root, "go.mod"):
        plans.append(_make_setup_plan("go dependencies", ("go", "mod", "download")))

    if _find_root_file(root, "Cargo.toml"):
        plans.append(_make_setup_plan("rust dependencies", ("cargo", "fetch")))

    return tuple(plans)


def _static_analysis_check(analysis: AnalysisReport) -> RebuildStep:
    critical = analysis.critical_findings()
    if critical:
        details = "Critical findings prevent a clean rebuild:\n" + "\n".join(
            f"- {finding.rule_id}: {finding.title}" for finding in critical
        )
        return RebuildStep(name="static analysis", status=CheckStatus.failed, details=details)
    return RebuildStep(
        name="static analysis",
        status=CheckStatus.passed,
        details="No critical reproducibility findings were detected.",
    )


def _execution_environment(cwd: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PWD"] = str(cwd)
    return environment


def _venv_python(sandbox: Path) -> Path:
    """Return the Python executable inside the disposable rebuild environment."""

    if os.name == "nt":
        return sandbox / ".rebuildpilot-venv" / "Scripts" / "python.exe"
    return sandbox / ".rebuildpilot-venv" / "bin" / "python"


def _python_argv(argv: tuple[str, ...], python_executable: Path) -> tuple[str, ...]:
    if argv and argv[0].casefold() == "python":
        return (str(python_executable), *argv[1:])
    return argv


def _python_runtime_step(sandbox: Path, timeout: int) -> RebuildStep:
    """Create the disposable Python environment used by setup and tests."""

    return _run_command(
        ("python", "-m", "venv", ".rebuildpilot-venv"),
        name="setup: python runtime",
        cwd=sandbox,
        timeout=timeout,
    )


def _run_command(
    argv: tuple[str, ...],
    *,
    name: str,
    cwd: Path,
    timeout: int,
) -> RebuildStep:
    command = _command_text(argv)
    executable = argv[0]
    if shutil.which(executable) is None:
        return RebuildStep(
            name=name,
            status=CheckStatus.failed,
            command=command,
            details=f"The required `{executable}` executable is not available on this machine.",
        )

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=_execution_environment(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        duration = round(time.perf_counter() - started, 3)
        output = _combined_output(error.stdout, error.stderr)
        details = f"Command exceeded the {timeout}-second timeout."
        if output:
            details += f"\n{output}"
        return RebuildStep(
            name=name,
            status=CheckStatus.failed,
            command=command,
            duration_seconds=duration,
            details=details,
        )
    except OSError as error:
        return RebuildStep(
            name=name,
            status=CheckStatus.failed,
            command=command,
            duration_seconds=round(time.perf_counter() - started, 3),
            details=f"Could not execute the command: {error}",
        )

    duration = round(time.perf_counter() - started, 3)
    output = _combined_output(completed.stdout, completed.stderr)
    details = f"Command exited with code {completed.returncode}."
    if output:
        details += f"\n{output}"
    return RebuildStep(
        name=name,
        status=CheckStatus.passed if completed.returncode == 0 else CheckStatus.failed,
        command=command,
        exit_code=completed.returncode,
        duration_seconds=duration,
        details=details,
    )


def _test_step(command: str, cwd: Path, timeout: int, python_executable: Path | None = None) -> RebuildStep:
    if command not in SUPPORTED_TEST_COMMANDS:
        return RebuildStep(
            name=f"test: {command}",
            status=CheckStatus.skipped,
            command=command,
            details="The detected command is not in RebuildPilot's safe rebuild allowlist.",
        )
    tokens = tuple(command.split())
    if python_executable is not None:
        tokens = _python_argv(tokens, python_executable)
    return _run_command(tokens, name=f"test: {command}", cwd=cwd, timeout=timeout)


def _no_tests_step() -> RebuildStep:
    return RebuildStep(
        name="tests",
        status=CheckStatus.failed,
        details="No deterministic test command was detected.",
    )


def _tests_blocked_steps(commands: list[str], details: str) -> tuple[RebuildStep, ...]:
    if not commands:
        return (_no_tests_step(),)
    return tuple(
        RebuildStep(
            name=f"test: {command}",
            status=CheckStatus.skipped,
            command=command,
            details=details,
        )
        for command in commands
    )


def _summary(passed: bool, checks: tuple[RebuildStep, ...]) -> str:
    if passed:
        return "Clean rebuild passed: static analysis, dependency setup, and a detected test command succeeded in an isolated copy."
    failures = sum(check.status is CheckStatus.failed for check in checks)
    return f"Clean rebuild failed with {failures} failed check(s); review the setup and test details."


def rebuild(target: Path, *, timeout: int = 120) -> RebuildResult:
    """Analyze and clean-rebuild ``target`` without executing in the target.

    The target is copied into a :class:`tempfile.TemporaryDirectory`. Setup
    commands run in order and stop after the first failure; detected tests run
    only when setup completed successfully. Missing executables are failures,
    while an absent setup plan is an explicit skip. A project cannot pass
    without at least one passing test command.
    """

    if timeout < 1:
        raise ValueError("Rebuild timeout must be at least 1 second")

    analysis = analyze(Path(target))
    root = Path(analysis.target_path)
    plans = build_setup_plan(root)
    static_analysis = _static_analysis_check(analysis)
    setup_steps: list[RebuildStep] = []
    test_steps: tuple[RebuildStep, ...]

    with tempfile.TemporaryDirectory(prefix="rebuildpilot-rebuild-") as temporary:
        sandbox = Path(temporary) / "project"
        try:
            shutil.copytree(
                root,
                sandbox,
                ignore=shutil.ignore_patterns(*IGNORED_DIRECTORIES),
                dirs_exist_ok=True,
            )
        except (OSError, shutil.Error) as error:
            setup_steps.append(
                RebuildStep(
                    name="rebuild sandbox",
                    status=CheckStatus.failed,
                    details=f"Could not create a temporary rebuild copy: {error}",
                )
            )
            test_steps = _tests_blocked_steps(
                analysis.likely_test_commands,
                "Tests were not run because the temporary rebuild copy could not be created.",
            )
        else:
            python_plans = [plan for plan in plans if plan.executable.casefold() == "python"]
            python_runtime: Path | None = None
            if python_plans or any(command.startswith("python ") for command in analysis.likely_test_commands):
                runtime_step = _python_runtime_step(sandbox, timeout)
                setup_steps.append(runtime_step)
                if runtime_step.status is CheckStatus.passed:
                    python_runtime = _venv_python(sandbox)

            if not plans:
                setup_steps.append(
                    RebuildStep(
                        name="dependency setup",
                        status=CheckStatus.skipped,
                        details="No supported dependency setup manifest was detected.",
                    )
                )
                setup_failed = any(step.status is CheckStatus.failed for step in setup_steps)
            else:
                setup_failed = any(step.status is CheckStatus.failed for step in setup_steps)
                if setup_failed:
                    setup_steps.extend(
                        RebuildStep(
                            name=f"setup: {plan.name}",
                            status=CheckStatus.skipped,
                            command=plan.command,
                            details="Setup was not run because Python runtime preparation failed.",
                        )
                        for plan in plans
                    )
                else:
                    for index, plan in enumerate(plans):
                        command = _python_argv(plan.argv, python_runtime) if python_runtime is not None else plan.argv
                        step = _run_command(
                            command,
                            name=f"setup: {plan.name}",
                            cwd=sandbox,
                            timeout=timeout,
                        )
                        setup_steps.append(step)
                        if step.status is CheckStatus.failed:
                            setup_failed = True
                            for remaining in plans[index + 1 :]:
                                setup_steps.append(
                                    RebuildStep(
                                        name=f"setup: {remaining.name}",
                                        status=CheckStatus.skipped,
                                        command=remaining.command,
                                        details="Setup was not run because an earlier setup command failed.",
                                    )
                                )
                            break

            if setup_failed:
                test_steps = _tests_blocked_steps(
                    analysis.likely_test_commands,
                    "Tests were not run because dependency setup failed.",
                )
            elif not analysis.likely_test_commands:
                test_steps = (_no_tests_step(),)
            else:
                test_steps = tuple(
                    _test_step(command, sandbox, timeout, python_runtime)
                    for command in analysis.likely_test_commands
                )

    checks = (static_analysis, *setup_steps, *test_steps)
    setup_failed = any(
        step.status is CheckStatus.failed
        for step in setup_steps
        if step.command is not None or step.name == "rebuild sandbox"
    )
    test_passed = any(step.status is CheckStatus.passed for step in test_steps)
    test_failed = any(step.status is CheckStatus.failed for step in test_steps)
    passed = (
        static_analysis.status is CheckStatus.passed
        and not setup_failed
        and test_passed
        and not test_failed
    )
    return RebuildResult(
        target_path=analysis.target_path,
        analysis=analysis,
        static_analysis=static_analysis,
        setup_plan=plans,
        setup=tuple(setup_steps),
        tests=test_steps,
        passed=passed,
        summary=_summary(passed, checks),
    )


clean_rebuild = rebuild
