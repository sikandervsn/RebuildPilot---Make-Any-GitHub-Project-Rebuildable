"""Typer command-line interface for RebuildPilot."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .models import ReportFormat
from .planner import plan
from .reporters import html as html_report
from .reporters import json_report, markdown, operations
from .scanner import analyze
from .validator import validate


app = typer.Typer(
    name="rebuildpilot",
    help="Inspect a local project for reproducibility risks and report actionable fixes.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main_callback() -> None:
    """RebuildPilot command group."""


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


@app.command("analyze")
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

    report = analyze(project_path)
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


@app.command("fix")
def fix_command(
    project_path: Annotated[Path, typer.Argument(help="Project directory for which to create a plan.")],
    plan_only: Annotated[
        bool,
        typer.Option("--plan", help="Create a non-mutating remediation plan (the only supported fix mode)."),
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
    """Recommend safe remediation steps; this command never edits the target."""

    _validate_target(project_path)
    _validate_output(project_path, output)
    if not plan_only:
        typer.echo("Error: only the non-mutating `fix --plan` mode is supported.", err=True)
        raise typer.Exit(code=2)

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


def main() -> None:
    app()
