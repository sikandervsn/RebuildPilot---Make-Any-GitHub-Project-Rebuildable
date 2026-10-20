"""Interactive terminal workbench for RebuildPilot."""

from __future__ import annotations

import contextlib
import itertools
import os
from pathlib import Path
import sys
import threading
from collections.abc import Iterator, Sequence

import typer

from .rebuild import rebuild
from .repair import repair
from .scanner import analyze
from .validator import validate
from .workspace import ProjectCandidate, discover_projects


_LIME = "\033[92m"
_CYAN = "\033[96m"
_DIM = "\033[90m"
_RESET = "\033[0m"
_SELECTED = "\033[1;97;42m"
_CLEAR_LINE = "\033[2K\r"


def _heading(text: str) -> None:
    typer.echo(f"\n{_LIME}{text}{_RESET}")


@contextlib.contextmanager
def _working(message: str, comments: Sequence[str] = ()) -> Iterator[None]:
    """Show progress while a synchronous project operation is running."""

    if not sys.stdout.isatty():
        yield
        return

    stop = threading.Event()
    status_messages = tuple(comments) or (message,)

    def spin() -> None:
        frames = itertools.cycle("|/-\\")
        statuses = itertools.cycle(status_messages)
        while not stop.is_set():
            frame = next(frames)
            status = next(statuses)
            if stop.is_set():
                return
            sys.stdout.write(f"\r{_CYAN}{frame}{_RESET} {status}...")
            sys.stdout.flush()
            stop.wait(0.45)

    worker = threading.Thread(target=spin, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()
        sys.stdout.write(f"{_CLEAR_LINE}{_LIME}✓{_RESET} {message}\n")
        sys.stdout.flush()


def _keyboard_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(
                msvcrt.getwch(), ""
            )
        return {"\r": "enter", "\x03": "interrupt", "q": "quit"}.get(key, key)

    import termios
    import tty

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        key = sys.stdin.read(1)
        if key == "\x1b":
            sequence = sys.stdin.read(2)
            return {"[A": "up", "[B": "down"}.get(sequence, "")
        return {"\r": "enter", "\x03": "interrupt", "q": "quit"}.get(key, key)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _choose_action(actions: Sequence[tuple[str, str]]) -> str:
    """Choose an action with arrow keys, falling back to typed input in tests."""

    if not _keyboard_available():
        typer.echo("Use Up/Down and Enter to choose:")
        for index, (_, label) in enumerate(actions, start=1):
            typer.echo(f"{index}. {label}")
        choice = typer.prompt("rebuildpilot", default="1").strip().lower()
        if choice.isdigit() and 1 <= int(choice) <= len(actions):
            return actions[int(choice) - 1][0]
        return choice

    selected = 0

    def render() -> None:
        typer.echo("\033[H\033[J", nl=False)
        typer.echo(f"{_CYAN}RebuildPilot{_RESET} - reproducibility workbench")
        typer.echo(f"{_DIM}↑/↓ choose  Enter select  q quit{_RESET}\n")
        for index, (_, label) in enumerate(actions):
            prefix = "❯ " if index == selected else "  "
            style = _SELECTED if index == selected else ""
            typer.echo(f"{style}{prefix}{label}{_RESET if style else ''}")

    render()
    while True:
        key = _read_key()
        if key == "up":
            selected = (selected - 1) % len(actions)
        elif key == "down":
            selected = (selected + 1) % len(actions)
        elif key == "enter":
            return actions[selected][0]
        elif key in {"quit", "interrupt"}:
            raise KeyboardInterrupt
        else:
            continue
        render()


def _project_path() -> Path:
    while True:
        entered = typer.prompt(
            "Project folder",
            default=str(Path.cwd()),
            show_default=False,
        )
        candidate = Path(entered).expanduser()
        if candidate.exists() and candidate.is_dir():
            projects = discover_projects(candidate)
            if not projects:
                typer.echo(
                    "No project was found there. Choose a folder with source code or a project manifest.",
                    err=True,
                )
                continue
            return _select_project(candidate, projects)
        typer.echo(f"That folder does not exist or is not a directory: {candidate}", err=True)


def _select_project(workspace: Path, projects: Sequence[ProjectCandidate]) -> Path:
    if len(projects) == 1:
        typer.echo(f"Found 1 project: {projects[0].path}")
        return projects[0].path

    typer.echo(f"Found {len(projects)} projects in {workspace}. Choose which one to analyze first.")
    actions = tuple((str(index), project.label) for index, project in enumerate(projects, start=1))
    selected = _choose_action(actions)
    if selected.isdigit() and 1 <= int(selected) <= len(projects):
        return projects[int(selected) - 1].path
    return projects[0].path


def _discover_starting_project(workspace: Path) -> Path | None:
    projects = discover_projects(workspace)
    if not projects:
        _heading("No project found")
        typer.echo(
            "This folder is empty or contains no recognizable source code or project manifest."
        )
        typer.echo("Use Change project folder to select a project directory, or exit.")
        return None
    return _select_project(workspace, projects)


def _show_report(root: Path) -> None:
    with _working(
        "Analyzing project",
        (
            "Reading project files",
            "Detecting project languages",
            "Checking dependency manifests",
            "Reviewing runtime and environment setup",
            "Prioritizing reproducibility findings",
        ),
    ):
        report = analyze(root)
    counts = report.counts_by_severity()
    typer.echo(f"\nProject: {report.target_path}")
    typer.echo(f"Type: {report.project_type}")
    typer.echo(f"Score: {_LIME}{report.score}/100{_RESET}")
    typer.echo(
        "Findings: "
        f"{counts['critical']} critical, {counts['high']} high, "
        f"{counts['medium']} medium, {counts['low']} low"
    )
    if not report.findings:
        typer.echo("No reproducibility findings were detected.")
        return
    for finding in report.findings:
        if finding.severity.value not in {"critical", "high"}:
            continue
        location = f" ({finding.file_path})" if finding.file_path else ""
        typer.echo(f"  [{finding.severity.value.upper()}] {finding.title}{location}")
        typer.echo(f"    {finding.remediation}")


def _repair_and_verify(root: Path) -> None:
    with _working(
        "Applying safe repairs",
        (
            "Reviewing safe repair candidates",
            "Updating reproducibility metadata",
            "Protecting existing files with backups",
        ),
    ):
        result = repair(root, apply=True, backup=True)
    typer.echo(result["summary"])
    changed = result["changed_files"]
    if changed:
        typer.echo("Changed files:")
        for path in changed:
            typer.echo(f"  - {path}")
    skipped = result["skipped_findings"]
    blocking = [item for item in skipped if item["severity"] in {"critical", "high"}]
    if blocking:
        typer.echo(
            f"{len(blocking)} critical/high finding(s) remain outside the safe repair scope.",
            err=True,
        )
        for item in blocking:
            location = f" ({item['file_path']})" if item.get("file_path") else ""
            typer.echo(f"  - {item['title']}{location}: {item['reason']}", err=True)

    _heading("Re-analyzing repaired project")
    _show_report(root)
    _heading("Validating project")
    with _working(
        "Validating in sandbox",
        (
            "Creating an isolated validation copy",
            "Checking project configuration",
            "Running detected test commands",
            "Collecting validation results",
        ),
    ):
        validation = validate(root)
    typer.echo(validation.summary)
    if not validation.passed:
        typer.echo("Validation details:")
        for check in validation.checks:
            if check.status.value != "passed":
                typer.echo(f"  - {check.name}: {check.details}")


def _clean_rebuild(root: Path) -> None:
    _heading("Running disposable clean rebuild")
    with _working(
        "Preparing dependencies and running tests",
        (
            "Creating a disposable rebuild workspace",
            "Preparing recognized dependencies",
            "Running the clean project checks",
            "Collecting rebuild results",
        ),
    ):
        result = rebuild(root)
    typer.echo(result.summary)
    if not result.passed:
        for test in result.tests:
            if test.status.value != "passed":
                typer.echo(f"  - {test.name}: {test.details}")


def run() -> None:
    """Run the interactive terminal workbench from any project folder."""

    typer.echo(f"{_CYAN}RebuildPilot{_RESET} - reproducibility workbench")
    typer.echo(f"{_DIM}Use the arrow keys to inspect, repair, and verify the current project.{_RESET}")
    workspace = Path.cwd().resolve()
    root = _discover_starting_project(workspace)

    actions = (
        ("analyze", "Analyze project"),
        ("fix", "Fix safe problems and verify"),
        ("validate", "Validate in sandbox"),
        ("rebuild", "Run clean rebuild"),
        ("change", "Change project folder"),
        ("exit", "Exit"),
    )
    while True:
        _heading(f"Workspace: {root or workspace}")
        try:
            choice = _choose_action(actions)
        except (EOFError, KeyboardInterrupt):
            typer.echo()
            return

        try:
            if choice == "analyze":
                if root is None:
                    typer.echo("No project is selected. Choose Change project folder first.")
                    continue
                _show_report(root)
            elif choice == "fix":
                if root is None:
                    typer.echo("No project is selected. Choose Change project folder first.")
                    continue
                _repair_and_verify(root)
            elif choice == "validate":
                if root is None:
                    typer.echo("No project is selected. Choose Change project folder first.")
                    continue
                with _working(
                    "Validating in sandbox",
                    (
                        "Creating an isolated validation copy",
                        "Checking project configuration",
                        "Running detected test commands",
                        "Collecting validation results",
                    ),
                ):
                    validation = validate(root)
                typer.echo(validation.summary)
                if not validation.passed:
                    for check in validation.checks:
                        if check.status.value != "passed":
                            typer.echo(f"  - {check.name}: {check.details}")
            elif choice == "rebuild":
                if root is None:
                    typer.echo("No project is selected. Choose Change project folder first.")
                    continue
                _clean_rebuild(root)
            elif choice == "change":
                workspace = Path(
                    typer.prompt("Workspace folder", default=str(workspace), show_default=False)
                ).expanduser().resolve()
                if not workspace.exists() or not workspace.is_dir():
                    typer.echo("That workspace does not exist or is not a directory.", err=True)
                    continue
                root = _discover_starting_project(workspace)
            elif choice == "exit":
                return
        except ValueError as error:
            typer.echo(f"Operation failed: {error}", err=True)
