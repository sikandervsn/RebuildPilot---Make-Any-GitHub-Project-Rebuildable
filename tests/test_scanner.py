from __future__ import annotations

from pathlib import Path

import pytest

from rebuildpilot.models import Finding, Severity
from rebuildpilot.scanner import analyze
from rebuildpilot.scoring import calculate_score


FIXTURE = Path(__file__).parent / "fixtures" / "sample-project"


def finding_ids(report) -> set[str]:
    return {finding.rule_id for finding in report.findings}


def test_sample_project_detects_expected_reproducibility_signals() -> None:
    report = analyze(FIXTURE)

    assert report.project_type == "Python"
    assert report.languages == ["Python"]
    assert report.dependency_manifests == ["pyproject.toml", "requirements.txt"]
    assert report.dependency_lockfiles == []
    assert report.environment_variables_used == ["DATABASE_URL"]
    assert report.environment_variables_documented == ["API_URL"]
    assert report.runtime_definitions == ["Dockerfile"]
    assert report.likely_test_commands == ["python -m pytest"]
    assert not report.git_repository
    assert "RP-DEPS-001" in finding_ids(report)
    assert "RP-ENV-002" in finding_ids(report)
    assert "RP-PATH-001" in finding_ids(report)
    assert "RP-DOC-002" in finding_ids(report)
    assert report.critical_findings()
    assert report.score < 100


def test_invalid_target_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        analyze(tmp_path / "missing")
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        analyze(file_path)


def test_dependency_lockfile_and_runtime_detection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "locked"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    (tmp_path / "requirements.lock").write_text("requests==2.32.0\n", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    report = analyze(tmp_path)

    assert report.dependency_lockfiles == ["requirements.lock"]
    assert set(report.runtime_files) == {".python-version", "pyproject.toml"}
    assert "RP-DEPS-001" not in finding_ids(report)
    assert "RP-RUNTIME-001" not in finding_ids(report)


def test_environment_missing_template_is_high_and_incomplete_template_is_medium(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('import os\nvalue = os.environ["TOKEN"]\n', encoding="utf-8")
    no_template = analyze(tmp_path)
    assert "RP-ENV-001" in finding_ids(no_template)

    (tmp_path / ".env.example").write_text("OTHER=value\n", encoding="utf-8")
    incomplete = analyze(tmp_path)
    assert "RP-ENV-002" in finding_ids(incomplete)
    assert incomplete.environment_variables_used == ["TOKEN"]


def test_runtime_definition_test_command_readme_and_git_detection(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run"}}', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("## Setup\nnpm install\n## Test\nnpm test\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "app.test.js").write_text("test('ok', () => {})", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    report = analyze(tmp_path)

    assert report.runtime_definitions == ["Dockerfile"]
    assert report.likely_test_commands == ["npm test"]
    assert report.git_repository
    assert "RP-DOC-003" in finding_ids(report)
    assert "RP-GIT-002" in finding_ids(report)


def test_ignored_directories_do_not_create_path_findings(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "bad.js").write_text('path = "C:\\Users\\someone\\cache"', encoding="utf-8")
    (tmp_path / "app.py").write_text("print('ok')", encoding="utf-8")
    report = analyze(tmp_path)

    assert not any(finding.file_path and finding.file_path.startswith("node_modules/") for finding in report.findings)


def test_unix_machine_specific_paths_are_detected(tmp_path: Path) -> None:
    (tmp_path / "paths.py").write_text(
        "cache = '/home/alice/project-cache'\nuser = '/Users/alice/project'\n", encoding="utf-8"
    )
    report = analyze(tmp_path)

    path_findings = [finding for finding in report.findings if finding.rule_id == "RP-PATH-001"]
    assert len(path_findings) == 2


def test_paths_in_tests_are_advisory_not_critical(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_paths.py").write_text(
        "fixture = 'C:\\\\Users\\\\developer\\\\fixture'\n", encoding="utf-8"
    )

    report = analyze(tmp_path)

    finding = next(item for item in report.findings if item.rule_id == "RP-PATH-001")
    assert finding.severity is Severity.medium
    assert not report.critical_findings()


def test_missing_lockfile_is_a_risk_not_a_completeness_failure(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "library", "version": "1.0.0"}', encoding="utf-8")

    report = analyze(tmp_path)

    finding = next(item for item in report.findings if item.rule_id == "RP-DEPS-001")
    assert finding.severity is Severity.medium


def test_unreadable_and_malformed_inputs_are_reported(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": ', encoding="utf-8")
    (tmp_path / "broken.py").write_bytes(b"value = '\xff'\n")
    report = analyze(tmp_path)

    assert "broken.py" in report.unreadable_files
    assert "RP-INPUT-001" in finding_ids(report)
    assert "RP-INPUT-002" in finding_ids(report)


def test_score_deductions_are_deterministic_and_explainable() -> None:
    findings = [
        Finding(
            rule_id="critical-rule",
            severity=Severity.critical,
            title="Critical",
            explanation="x",
            remediation="y",
        ),
        Finding(
            rule_id="medium-rule",
            severity=Severity.medium,
            title="Medium",
            explanation="x",
            remediation="y",
        ),
    ]
    score, reasons = calculate_score(findings)

    assert score == 67
    assert [(reason.rule_id, reason.points) for reason in reasons] == [
        ("critical-rule", 25),
        ("medium-rule", 8),
    ]
