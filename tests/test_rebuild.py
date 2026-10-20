from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import rebuildpilot.rebuild as rebuild_module
from rebuildpilot.models import CheckStatus
from rebuildpilot.rebuild import build_setup_plan, rebuild


def _python_project(root: Path, *, requirements: str = "requirements.lock") -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "offline-sample"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (root / requirements).write_text("", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_ok.py").write_text(
        "from pathlib import Path\n\n\n"
        "def test_ok():\n"
        "    Path('rebuild-marker.txt').write_text('created in sandbox', encoding='utf-8')\n",
        encoding="utf-8",
    )


def test_rebuild_runs_setup_and_tests_only_in_the_temporary_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _python_project(tmp_path)

    calls: list[tuple[list[str], Path]] = []

    def fake_run(argv: list[str], *, cwd: Path, **_: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, cwd))
        (cwd / "rebuild-marker.txt").write_text("created in sandbox", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(rebuild_module.shutil, "which", lambda _: "fake-executable")
    monkeypatch.setattr(rebuild_module.subprocess, "run", fake_run)

    result = rebuild(tmp_path)

    assert result.passed
    assert result.setup[0].name == "setup: python runtime"
    assert result.setup[0].status is CheckStatus.passed
    assert result.setup[1].command.endswith(
        "-m pip install --no-input --disable-pip-version-check -r requirements.lock"
    )
    assert result.tests
    assert len(result.as_dict()["checks"]) == len(result.checks)
    assert result.tests[0].status is CheckStatus.passed
    assert result.tests[0].command.endswith("-m pytest")
    assert not (tmp_path / "rebuild-marker.txt").exists()
    assert calls[0][0] == ["python", "-m", "venv", ".rebuildpilot-venv"]
    assert calls[1][0][1:] == ["-m", "pip", "install", "--no-input", "--disable-pip-version-check", "-r", "requirements.lock"]
    assert calls[2][0][1:] == ["-m", "pytest"]
    assert all(cwd != tmp_path.resolve() for _, cwd in calls)
    assert calls[0][1] == calls[1][1]


def test_setup_plan_covers_supported_manifests_and_python_precedence(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts": {"test": "node test"}}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module example\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'sample'\n", encoding="utf-8")

    plans = build_setup_plan(tmp_path)

    assert [plan.command for plan in plans] == [
        "python -m pip install --no-input --disable-pip-version-check -r requirements.lock",
        "npm ci",
        "go mod download",
        "cargo fetch",
    ]
    assert plans[0].as_dict()["arguments"] == [
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "-r",
        "requirements.lock",
    ]

    (tmp_path / "requirements.lock").unlink()
    (tmp_path / "package-lock.json").unlink()
    fallback_plans = build_setup_plan(tmp_path)

    assert [plan.command for plan in fallback_plans] == [
        "python -m pip install --no-input --disable-pip-version-check -r requirements.txt",
        "npm install",
        "go mod download",
        "cargo fetch",
    ]


def test_pyproject_only_uses_package_install_setup(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")

    plans = build_setup_plan(tmp_path)

    assert [plan.command for plan in plans] == [
        "python -m pip install --no-input --disable-pip-version-check ."
    ]


def test_missing_setup_executable_is_failed_and_tests_are_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _python_project(tmp_path)
    monkeypatch.setattr(rebuild_module.shutil, "which", lambda _: None)

    result = rebuild(tmp_path)

    assert not result.passed
    assert result.setup[0].status is CheckStatus.failed
    assert "required `python` executable" in result.setup[0].details
    assert result.tests[0].status is CheckStatus.skipped


def test_no_setup_or_tests_is_explicit_and_cannot_pass(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("A dependency-free project.\n", encoding="utf-8")

    result = rebuild(tmp_path)

    assert not result.passed
    assert result.setup[0].status is CheckStatus.skipped
    assert result.tests[0].status is CheckStatus.failed
    payload = result.as_json_dict()
    json.dumps(payload)
    assert payload["setup"][0]["status"] == "skipped"
    assert payload["tests"][0]["status"] == "failed"


def test_command_output_is_captured_and_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _python_project(tmp_path)

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="x" * 5_000, stderr="")

    monkeypatch.setattr(rebuild_module.shutil, "which", lambda _: "fake-executable")
    monkeypatch.setattr(rebuild_module.subprocess, "run", fake_run)

    result = rebuild(tmp_path)

    assert result.passed
    assert result.setup[0].status is CheckStatus.passed
    assert result.tests[0].status is CheckStatus.passed
    assert "...[output truncated]" in result.setup[0].details
    assert len(result.setup[0].details) < 4_100
