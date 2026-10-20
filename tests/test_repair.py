from __future__ import annotations

import json
from pathlib import Path

from rebuildpilot.repair import repair


def test_plan_does_not_apply_repairs_and_returns_serializable_scores(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('import os\nTOKEN = os.environ["TOKEN"]\n', encoding="utf-8")
    (tmp_path / ".env.example").write_bytes(b"OTHER=value\r\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "planned"\nrequires-python = "==3.12.4"\n', encoding="utf-8"
    )

    result = repair(tmp_path)

    assert result["changed_files"] == []
    assert {item["path"] for item in result["planned_changes"]} == {".env.example", ".python-version"}
    assert result["before_score"] == result["after_score"]
    assert "Repair planned" in result["summary"]
    assert (tmp_path / ".env.example").read_bytes() == b"OTHER=value\r\n"
    assert not (tmp_path / ".python-version").exists()
    json.dumps(result)


def test_environment_repair_appends_empty_names_and_preserves_crlf(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('import os\nvalue = os.environ["TOKEN"]\n', encoding="utf-8")
    (tmp_path / ".env.example").write_bytes(b"EXISTING=value\r\n")

    result = repair(tmp_path, apply=True)

    assert result["changed_files"] == [".env.example"]
    assert (tmp_path / ".env.example").read_bytes() == b"EXISTING=value\r\nTOKEN=\r\n"
    assert result["after_score"] > result["before_score"]
    assert "Repair applied" in result["summary"]
    assert not (tmp_path / ".python-version").exists()


def test_environment_repair_creates_non_secret_template_when_missing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'import os\nvalue = os.environ["TOKEN"]\n', encoding="utf-8"
    )

    result = repair(tmp_path, apply=True)

    assert result["changed_files"] == [".env.example"]
    assert (tmp_path / ".env.example").read_text(encoding="utf-8") == "TOKEN=\n"
    assert result["after_score"] > result["before_score"]


def test_exact_python_pin_creates_single_major_minor_version_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pinned"\nrequires-python = "==3.11.7"\n', encoding="utf-8"
    )

    result = repair(tmp_path, apply=True)

    assert result["changed_files"] == [".python-version"]
    assert (tmp_path / ".python-version").read_text(encoding="utf-8") == "3.11\n"
    assert result["after_score"] == result["before_score"]


def test_ranges_do_not_trigger_unsafe_or_unrelated_changes(tmp_path: Path) -> None:
    source = "cache = '/home/alice/project-cache'\n"
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "ranged"\nrequires-python = ">=3.11,<3.13"\n', encoding="utf-8"
    )

    result = repair(tmp_path, apply=True)

    assert result["changed_files"] == []
    assert not (tmp_path / ".python-version").exists()
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == source
    assert not (tmp_path / "requirements.lock").exists()
    assert any(item["rule_id"] == "RP-PATH-001" for item in result["skipped_findings"])
    assert any(item["rule_id"] == "RP-RUNTIME-001" for item in result["skipped_findings"])


def test_backup_is_written_before_mutation_and_never_overwritten(tmp_path: Path) -> None:
    source = 'import os\nvalue = os.environ["TOKEN"]\n'
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    original = b"EXISTING=value\n"
    (tmp_path / ".env.example").write_bytes(original)

    first = repair(tmp_path, apply=True, backup=True)

    backup = tmp_path / ".env.example.rebuildpilot.bak"
    assert first["changed_files"] == [".env.example"]
    assert first["backups"] == [".env.example.rebuildpilot.bak"]
    assert backup.read_bytes() == original

    current = (tmp_path / ".env.example").read_bytes()
    (tmp_path / "app.py").write_text(source + 'other = os.environ["SECOND"]\n', encoding="utf-8")
    second = repair(tmp_path, apply=True, backup=True)

    assert second["changed_files"] == []
    assert (tmp_path / ".env.example").read_bytes() == current
    assert backup.read_bytes() == original
    assert any("Backup already exists" in item["reason"] for item in second["skipped_findings"])
