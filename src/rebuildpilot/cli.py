"""Typer command-line interface for RebuildPilot."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .dashboard import serve
from .models import ReportFormat
from .planner import plan
from .repository import (
    commit_repository,
    diff_repository,
    onboard_repository,
    publish_repository,
)
from .rebuild import rebuild as clean_rebuild
from .repair import repair as apply_repairs
from .reporters import html as html_report
from .reporters import execution, json_report, markdown, operations
from .scanner import analyze
from .validator import validate
from .terminal import run as run_terminal


app = typer.Typer(
    name="rebuildpilot",
    help="Inspect a local project for reproducibility risks and report actionable fixes.",
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """RebuildPilot command group."""

    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        run_terminal()


@app.command("chat")
def chat_command() -> None:
    """Open the interactive terminal workbench."""

    run_terminal()


@app.command("desktop")
def desktop_command() -> None:
    """Open the native PySide6 desktop application."""

    try:
        from .desktop import run

        raise typer.Exit(code=run())
    except RuntimeError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


def _validate_target(project_path: Path) -> None:
    if not project_path.exists():
        typer.echo(f"Error: target path does not exist: {project_path}", err=True)
        raise typer.Exit(code=2)
    if not project_path.is_dir():
        typer.echo(f"Error: target path is not a directory: {project_path}", err=True)
        raise typer.Exit(code=2)


def _validate_output(project_path: Path, output: Path | None) -> None:
    if output is None:
        return
    target_root = project_path.resolve()
    output_root = output.resolve()
    if output_root == target_root or target_root in output_root.parents:
        typer.echo("Error: --output must not be inside the analyzed project.", err=True)
        raise typer.Exit(code=2)
    if output.exists() and not output.is_dir():
        typer.echo("Error: --output must be a directory.", err=True)
        raise typer.Exit(code=2)


def _write_or_echo(rendered: str, output: Path | None, filename: str) -> None:
    if output is None:
        typer.echo(rendered, nl=False)
        return
    try:
        output.mkdir(parents=True, exist_ok=True)
        destination = output / filename
        destination.write_text(rendered, encoding="utf-8")
    except OSError as error:
        typer.echo(f"Error: could not write report: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Report written to {destination}")


def _analysis_render(report, format: ReportFormat) -> tuple[str, str]:
    if format is ReportFormat.json:
        return json_report.render(report), "rebuildpilot-report.json"
    if format is ReportFormat.html:
        return html_report.render(report), "rebuildpilot-report.html"
    return markdown.render(report), "rebuildpilot-report.md"


def _rebuild_render(result, format: ReportFormat) -> tuple[str, str]:
    if format is ReportFormat.json:
        return json_report.render_payload(result.as_json_dict()), "rebuildpilot-rebuild.json"
    if format is ReportFormat.html:
        return execution.rebuild_html(result), "rebuildpilot-rebuild.html"
    return execution.rebuild_markdown(result), "rebuildpilot-rebuild.md"


def _repair_render(payload: dict, format: ReportFormat) -> tuple[str, str]:
    if format is ReportFormat.json:
        return json_report.render_payload(payload), "rebuildpilot-repair.json"
    if format is ReportFormat.html:
        return execution.repair_html(payload), "rebuildpilot-repair.html"
    return execution.repair_markdown(payload), "rebuildpilot-repair.md"


@app.command("analyze")
@app.command("analyse")
def analyze_command(
    project_path: Annotated[Path, typer.Argument(help="Project directory to inspect.")],
    format: Annotated[
        ReportFormat,
        typer.Option("--format", case_sensitive=False, help="Report format: markdown, json, or html."),
    ] = ReportFormat.markdown,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Directory in which to write the report file."),
    ] = None,
) -> None:
    """Analyze PROJECT_PATH without modifying it."""

    _validate_target(project_path)
    _validate_output(project_path, output)

    try:
        report = analyze(project_path)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    rendered, filename = _analysis_render(report, format)
    _write_or_echo(rendered, output, filename)

    if report.critical_findings():
        raise typer.Exit(code=1)


@app.command("validate")
def validate_command(
    project_path: Annotated[Path, typer.Argument(help="Project directory to validate.")],
    format: Annotated[
        ReportFormat,
        typer.Option("--format", case_sensitive=False, help="Report format: markdown, json, or html."),
    ] = ReportFormat.markdown,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Directory in which to write the validation report."),
    ] = None,
    skip_tests: Annotated[
        bool,
        typer.Option("--skip-tests", help="Do not execute detected test commands."),
    ] = False,
    docker: Annotated[
        bool,
        typer.Option("--docker", help="Build the detected Dockerfile in the validation sandbox."),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", min=1, help="Maximum seconds allowed for each command."),
    ] = 120,
) -> None:
    """Validate static signals and detected local test commands without changing the target."""

    _validate_target(project_path)
    _validate_output(project_path, output)
    try:
        report = validate(project_path, run_tests=not skip_tests, docker=docker, timeout=timeout)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    if format is ReportFormat.json:
        rendered = json_report.render(report)
        filename = "rebuildpilot-validation.json"
    elif format is ReportFormat.html:
        rendered = operations.validation_html(report)
        filename = "rebuildpilot-validation.html"
    else:
        rendered = operations.validation_markdown(report)
        filename = "rebuildpilot-validation.md"
    _write_or_echo(rendered, output, filename)
    if not report.passed:
        raise typer.Exit(code=1)


@app.command("rebuild")
def rebuild_command(
    project_path: Annotated[Path, typer.Argument(help="Project directory to rebuild in a temporary copy.")],
    format: Annotated[
        ReportFormat,
        typer.Option("--format", case_sensitive=False, help="Report format: markdown, json, or html."),
    ] = ReportFormat.markdown,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Directory in which to write the rebuild report."),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option("--timeout", min=1, help="Maximum seconds allowed for each setup or test command."),
    ] = 120,
) -> None:
    """Install recognized dependencies and run tests in a disposable copy."""

    _validate_target(project_path)
    _validate_output(project_path, output)
    try:
        result = clean_rebuild(project_path, timeout=timeout)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    rendered, filename = _rebuild_render(result, format)
    _write_or_echo(rendered, output, filename)
    if not result.passed:
        raise typer.Exit(code=1)


@app.command("fix")
def fix_command(
    project_path: Annotated[Path, typer.Argument(help="Project directory for which to create a plan.")],
    plan_only: Annotated[
        bool,
        typer.Option("--plan", help="Create a non-mutating recommendation plan."),
    ] = False,
    apply_changes: Annotated[
        bool,
        typer.Option("--apply", help="Apply only bounded, deterministic metadata repairs."),
    ] = False,
    backup: Annotated[
        bool,
        typer.Option("--backup", help="Back up each file before an applied repair."),
    ] = False,
    format: Annotated[
        ReportFormat,
        typer.Option("--format", case_sensitive=False, help="Report format: markdown, json, or html."),
    ] = ReportFormat.markdown,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Directory in which to write the remediation plan."),
    ] = None,
) -> None:
    """Plan remediation or apply bounded deterministic metadata repairs."""

    _validate_target(project_path)
    _validate_output(project_path, output)
    if plan_only and apply_changes:
        typer.echo("Error: --plan and --apply cannot be used together.", err=True)
        raise typer.Exit(code=2)
    if backup and not apply_changes:
        typer.echo("Error: --backup requires --apply.", err=True)
        raise typer.Exit(code=2)
    if not plan_only and not apply_changes:
        typer.echo("Error: choose either `fix --plan` or `fix --apply`.", err=True)
        raise typer.Exit(code=2)

    if apply_changes:
        repair_result = apply_repairs(project_path, apply=True, backup=backup)
        rendered, filename = _repair_render(repair_result, format)
        _write_or_echo(rendered, output, filename)
        blocking = any(item["severity"] in {"critical", "high"} for item in repair_result["skipped_findings"])
        if blocking:
            raise typer.Exit(code=1)
        return

    remediation_plan = plan(project_path)
    if format is ReportFormat.json:
        rendered = json_report.render(remediation_plan)
        filename = "rebuildpilot-fix-plan.json"
    elif format is ReportFormat.html:
        rendered = operations.plan_html(remediation_plan)
        filename = "rebuildpilot-fix-plan.html"
    else:
        rendered = operations.plan_markdown(remediation_plan)
        filename = "rebuildpilot-fix-plan.md"
    _write_or_echo(rendered, output, filename)
    if remediation_plan.analysis.critical_findings():
        raise typer.Exit(code=1)


@app.command("dashboard")
def dashboard_command(
    host: Annotated[
        str,
        typer.Option("--host", help="Interface for the local dashboard server."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=0, max=65535, help="Port for the local dashboard server; 0 selects a free port."),
    ] = 8765,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Start the server without opening a browser window."),
    ] = False,
) -> None:
    """Open the local GUI dashboard in a browser."""

    serve(host=host, port=port, open_browser=not no_browser)


@app.command("onboard")
def onboard_command(
    repository_url: Annotated[str, typer.Argument(help="GitHub HTTPS or SSH clone URL.")],
    branch: Annotated[
        str | None,
        typer.Option("--branch", help="Branch to clone before creating the repair branch."),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option("--timeout", min=1, help="Maximum seconds allowed for each setup or test command."),
    ] = 120,
    cleanup: Annotated[
        bool,
        typer.Option("--cleanup", help="Remove the cloned workspace after verification; disables follow-up diff/commit/publish commands."),
    ] = False,
) -> None:
    """Clone a GitHub repository, apply safe fixes, and verify a clean rebuild."""

    try:
        result = onboard_repository(repository_url, branch=branch, timeout=timeout)
        typer.echo(f"Repository cloned to: {result.workspace.root}")
        typer.echo(f"Repair branch: {result.workspace.branch}")
        typer.echo(result.rebuild_result.summary)
        typer.echo(f"Before score: {result.analysis_before.score}/100")
        typer.echo(f"After score: {result.analysis_after.score}/100")
        typer.echo(f"Review changes with: rebuildpilot diff {result.workspace.root}")
        typer.echo(f"Commit with: rebuildpilot commit {result.workspace.root} -m \"Improve reproducibility\"")
        if cleanup:
            result.workspace.cleanup()
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


@app.command("diff")
def diff_command(
    project_path: Annotated[Path, typer.Argument(help="Cloned repository directory.")],
) -> None:
    """Show changes made in the current repository workspace."""

    _validate_target(project_path)
    try:
        typer.echo(diff_repository(project_path))
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


@app.command("commit")
def commit_command(
    project_path: Annotated[Path, typer.Argument(help="Cloned repository directory.")],
    message: Annotated[str, typer.Option("-m", "--message", help="Commit message.")],
) -> None:
    """Commit reviewed changes in a cloned repository."""

    _validate_target(project_path)
    try:
        commit_hash = commit_repository(project_path, message)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Committed {commit_hash}")


@app.command("publish")
def publish_command(
    project_path: Annotated[Path, typer.Argument(help="Cloned repository directory.")],
    remote: Annotated[str, typer.Option("--remote", help="Git remote to push.") ] = "origin",
    pull_request: Annotated[
        bool,
        typer.Option("--pull-request", help="Create a pull request with the GitHub CLI after pushing."),
    ] = False,
    new_repository: Annotated[
        str | None,
        typer.Option("--new-repository", help="Create this new GitHub repository instead of using the existing remote."),
    ] = None,
    public: Annotated[
        bool,
        typer.Option("--public", help="Make a newly created repository public; new repositories are private by default."),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Explicitly confirm the remote push."),
    ] = False,
) -> None:
    """Push reviewed changes, optionally creating a GitHub pull request."""

    _validate_target(project_path)
    if not confirm:
        typer.echo("Refusing to push without --confirm. Review `rebuildpilot diff` first.", err=True)
        raise typer.Exit(code=2)
    try:
        typer.echo(
            publish_repository(
                project_path,
                remote=remote,
                create_pr=pull_request,
                new_repository=new_repository,
                private=not public,
            )
        )
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


def main() -> None:
    app()
