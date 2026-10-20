from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rebuildpilot.validator as validator_module
from rebuildpilot.cli import app
from rebuildpilot.reporters import json_report, markdown
from rebuildpilot.scanner import analyze
from rebuildpilot.validator import validate
from rebuildpilot.dashboard import _repair_summary
from rebuildpilot.workspace import discover_projects


FIXTURE = Path(__file__).parent / "fixtures" / "sample-project"
HEALTHY_FIXTURE = Path(__file__).parent / "fixtures" / "healthy-project"
runner = CliRunner()


def test_markdown_and_json_reports_are_rendered() -> None:
    report = analyze(FIXTURE)
    markdown_text = markdown.render(report)
    json_text = json_report.render(report)

    assert "# RebuildPilot report" in markdown_text
    assert "RP-PATH-001" in markdown_text
    parsed = json.loads(json_text)
    assert parsed["score"] == report.score
    assert parsed["findings"]


def test_cli_help_and_invalid_target() -> None:
    help_result = runner.invoke(app, ["--help"])
    invalid_result = runner.invoke(app, ["analyze", "does-not-exist"])
    british_result = runner.invoke(app, ["analyse", str(HEALTHY_FIXTURE), "--format", "json"])

    assert help_result.exit_code == 0
    assert "analyze" in help_result.stdout
    assert invalid_result.exit_code == 2
    assert "does not exist" in invalid_result.stderr
    assert british_result.exit_code == 0
    assert '"score": 97' in british_result.stdout


def test_interactive_terminal_starts_in_current_project_and_exits() -> None:
    result = runner.invoke(app, ["chat"], input="1\n6\n")

    assert result.exit_code == 0
    assert "RebuildPilot" in result.stdout
    assert "Workspace:" in result.stdout
    assert "6. Exit" in result.stdout
    assert "Use Up/Down and Enter to choose:" in result.stdout


def test_empty_folder_is_rejected_before_analysis(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 2
    assert "No project files were found" in result.stderr


def test_workspace_discovery_lists_multiple_project_roots(tmp_path: Path) -> None:
    (tmp_path / "python-app").mkdir()
    (tmp_path / "python-app" / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    (tmp_path / "web-app").mkdir()
    (tmp_path / "web-app" / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")

    projects = discover_projects(tmp_path)

    assert [project.path.name for project in projects] == ["python-app", "web-app"]


def test_cli_returns_nonzero_for_critical_and_writes_json(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    result = runner.invoke(app, ["analyze", str(FIXTURE), "--format", "json", "--output", str(output)])

    assert result.exit_code == 1
    report_path = output / "rebuildpilot-report.json"
    assert report_path.exists()
    assert json.loads(report_path.read_text(encoding="utf-8"))["score"] < 100


def test_cli_returns_zero_when_no_critical_finding_exists(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "clean"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    (tmp_path / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("## Setup\nInstall it.\n## Test\npython -m pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    result = runner.invoke(app, ["analyze", str(tmp_path), "--format", "markdown"])

    assert result.exit_code == 0
    assert "Reproducibility score" in result.stdout


def test_healthy_fixture_has_no_actionable_findings_and_validates() -> None:
    report = analyze(HEALTHY_FIXTURE)
    validation = validate(HEALTHY_FIXTURE)

    assert report.score >= 90
    assert not any(finding.severity.value in {"critical", "high"} for finding in report.findings)
    assert not report.critical_findings()
    assert validation.passed
    assert any(check.name == "test: python -m pytest" and check.status.value == "passed" for check in validation.checks)


def test_validate_cli_runs_tests_and_writes_json(tmp_path: Path) -> None:
    output = tmp_path / "validation"
    result = runner.invoke(
        app,
        ["validate", str(HEALTHY_FIXTURE), "--format", "json", "--output", str(output)],
    )

    assert result.exit_code == 0
    payload = json.loads((output / "rebuildpilot-validation.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert any(check["status"] == "passed" for check in payload["checks"])


def test_validate_reports_a_failing_detected_test_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "failing-sample"\nversion = "0.1.0"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_failure.py").write_text(
        "def test_failure():\n    assert False\n", encoding="utf-8"
    )

    report = validate(tmp_path)

    assert not report.passed
    assert any(check.name == "test: python -m pytest" and check.status.value == "failed" for check in report.checks)


def test_html_report_and_plan_are_available_without_mutating_target() -> None:
    html_result = runner.invoke(app, ["analyze", str(HEALTHY_FIXTURE), "--format", "html"])
    plan_result = runner.invoke(app, ["fix", str(FIXTURE), "--plan", "--format", "json"])

    assert html_result.exit_code == 0
    assert "<!doctype html>" in html_result.stdout
    assert "RebuildPilot report" in html_result.stdout
    assert plan_result.exit_code == 1
    plan_payload = json.loads(plan_result.stdout)
    assert plan_payload["items"]
    assert all(item["plan_only"] for item in plan_payload["items"])
    assert (FIXTURE / "src" / "app.py").read_text(encoding="utf-8").count("C:\\Users") == 1


def test_dashboard_repair_summary_supports_older_payloads() -> None:
    summary = _repair_summary(
        {
            "apply_requested": False,
            "planned_changes": [{"path": ".python-version"}],
            "before_score": 80,
            "after_score": 80,
        }
    )

    assert summary == "Repair planned: 1 change(s); score 80/100 -> 80/100"


def test_dashboard_start_view_clears_stale_projects_before_loading() -> None:
    from rebuildpilot.dashboard import _HTML

    assert "state.root=null" in _HTML
    assert "loadedProject').classList.remove('ready')" in _HTML
    assert "Cloning and preparing the GitHub repository" in _HTML
    assert "Source: '+source" in _HTML


def test_validate_fails_when_a_detected_test_executable_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "missing-runner"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(validator_module.shutil, "which", lambda _: None)

    report = validate(tmp_path)

    assert not report.passed
    assert any(
        check.name == "test: python -m pytest"
        and check.status.value == "failed"
        and "not available" in check.details
        for check in report.checks
    )


def test_fix_apply_repairs_bounded_metadata_and_writes_a_repair_report(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('import os\nvalue = os.environ["TOKEN"]\n', encoding="utf-8")
    (tmp_path / ".env.example").write_text("EXISTING=value\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "repairable"\nrequires-python = "==3.12.4"\n', encoding="utf-8"
    )
    (tmp_path / "requirements.lock").write_text("", encoding="utf-8")
    output = tmp_path.parent / "repair-report"

    result = runner.invoke(
        app,
        ["fix", str(tmp_path), "--apply", "--format", "json", "--output", str(output)],
    )

    assert result.exit_code == 0
    assert (tmp_path / ".env.example").read_text(encoding="utf-8") == "EXISTING=value\nTOKEN=\n"
    assert (tmp_path / ".python-version").read_text(encoding="utf-8") == "3.12\n"
    payload = json.loads((output / "rebuildpilot-repair.json").read_text(encoding="utf-8"))
    assert payload["changed_files"] == [".env.example", ".python-version"]
    assert payload["after_score"] >= payload["before_score"]


def test_rebuild_cli_writes_a_failure_report_when_no_test_exists(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("A dependency-free project.\n", encoding="utf-8")
    output = tmp_path.parent / "rebuild-report"

    result = runner.invoke(
        app,
        ["rebuild", str(tmp_path), "--format", "json", "--output", str(output)],
    )

    assert result.exit_code == 1
    payload = json.loads((output / "rebuildpilot-rebuild.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["tests"][0]["status"] == "failed"
