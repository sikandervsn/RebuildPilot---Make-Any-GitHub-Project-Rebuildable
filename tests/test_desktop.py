from __future__ import annotations

import pytest

from rebuildpilot.ai import PROVIDERS, build_advice_prompt, provider_by_key, redact_text
from rebuildpilot.scanner import analyze
from rebuildpilot.desktop import _tree_diff, _tree_diffs


def test_cloud_ai_providers_are_opt_in_and_have_environment_keys() -> None:
    assert [provider.key for provider in PROVIDERS] == ["gemini", "groq", "openrouter"]
    assert all(provider.environment_key for provider in PROVIDERS)
    assert provider_by_key("disabled") is None


def test_desktop_reports_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    import rebuildpilot.desktop as desktop

    real_import = __import__("builtins").__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("PySide6"):
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(__import__("builtins"), "__import__", blocked_import)
    with pytest.raises(RuntimeError, match="rebuildpilot\\[desktop\\]"):
        desktop._load_qt()


def test_ai_context_redacts_secrets_and_excludes_env_files(tmp_path) -> None:
    (tmp_path / ".env").write_text("TOKEN=do-not-send\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        'API_KEY = "secret-value"\nvalue = "safe"\n', encoding="utf-8"
    )
    report = analyze(tmp_path)

    prompt, selected = build_advice_prompt(tmp_path, report)

    assert "secret-value" not in prompt
    assert "do-not-send" not in prompt
    assert ".env" not in selected
    assert "[REDACTED_SECRET]" in redact_text('API_KEY="secret-value"')


def test_ai_context_contains_findings_without_uploading_unselected_files(tmp_path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("private unrelated notes\n", encoding="utf-8")
    report = analyze(tmp_path)

    prompt, selected = build_advice_prompt(tmp_path, report)

    assert "private unrelated notes" not in prompt
    assert "Findings:" in prompt
    assert isinstance(selected, list)


def test_whole_project_ai_context_includes_readable_files_but_excludes_secrets_and_generated_data(
    tmp_path,
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("cross-file context\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=do-not-send\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    report = analyze(tmp_path)

    prompt, selected = build_advice_prompt(tmp_path, report, include_all_files=True)

    assert "cross-file context" in prompt
    assert "do-not-send" not in prompt
    assert "ignored.js" not in selected
    assert "notes.txt" in selected
    assert "Review mode: whole project" in prompt


def test_repair_diff_is_split_by_changed_file(tmp_path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "one.txt").write_text("old\n", encoding="utf-8")
    (after / "one.txt").write_text("new\n", encoding="utf-8")
    (after / "two.txt").write_text("added\n", encoding="utf-8")

    diffs = _tree_diffs(before, after)

    assert set(diffs) == {"one.txt", "two.txt"}
    assert "one.txt" in _tree_diff(before, after)
    assert "new" in diffs["one.txt"]
