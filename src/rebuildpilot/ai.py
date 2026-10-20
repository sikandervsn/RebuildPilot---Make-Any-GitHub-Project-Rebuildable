"""Opt-in cloud AI provider metadata and request helpers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from .models import AnalysisReport


@dataclass(frozen=True)
class AIProvider:
    key: str
    name: str
    model: str
    endpoint: str
    environment_key: str
    free_tier_note: str


PROVIDERS = (
    AIProvider(
        "gemini",
        "Google Gemini",
        "gemini-2.0-flash",
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "GEMINI_API_KEY",
        "Free tier availability and limits depend on the current Google account and region.",
    ),
    AIProvider(
        "groq",
        "Groq",
        "llama-3.3-70b-versatile",
        "https://api.groq.com/openai/v1/chat/completions",
        "GROQ_API_KEY",
        "Free developer limits apply and may change.",
    ),
    AIProvider(
        "openrouter",
        "OpenRouter",
        "openai/gpt-oss-20b:free",
        "https://openrouter.ai/api/v1/chat/completions",
        "OPENROUTER_API_KEY",
        "Free-model rate limits and provider availability apply.",
    ),
)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization|private[_-]?key)\b\s*[:=]\s*[^\s,;]+"
)
_EXCLUDED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}
_EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".env.development"}
_BINARY_SUFFIXES = {
    ".7z", ".bin", ".db", ".dll", ".dylib", ".exe", ".gif", ".ico", ".jpg", ".jpeg",
    ".lock", ".mp3", ".mp4", ".parquet", ".pdf", ".png", ".pyc", ".so", ".sqlite",
    ".tar", ".ttf", ".wav", ".webp", ".whl", ".zip",
}
MAX_FULL_PROJECT_FILES = 80
MAX_FULL_PROJECT_CHARS = 120_000


def provider_by_key(key: str) -> AIProvider | None:
    return next((provider for provider in PROVIDERS if provider.key == key), None)


def redact_text(text: str) -> str:
    """Remove common secret assignments before cloud transmission."""

    return _SECRET_PATTERN.sub("[REDACTED_SECRET]", text)


def build_advice_prompt(
    root: Path,
    report: AnalysisReport,
    *,
    include_all_files: bool = False,
) -> tuple[str, list[str]]:
    """Build redacted AI context from findings and optionally the whole project."""

    selected: list[str] = []
    sections: list[str] = [
        "You are a senior software repair engineer reviewing a real project.",
        "Inspect the supplied files as one connected codebase, not as isolated snippets.",
        "Trace imports, configuration, dependency versions, entry points, data/model paths, "
        "platform assumptions, and test/build commands across files.",
        "Do not invent credentials or destructive commands. Do not claim a problem is confirmed "
        "unless the supplied project evidence supports it.",
        "Return: (1) executive diagnosis, (2) confirmed problems ranked by severity, "
        "(3) likely root cause and file/line evidence, (4) smallest safe repair, "
        "(5) exact verification commands, and (6) questions or missing evidence.",
        f"Project type: {report.project_type}",
        f"Languages: {', '.join(report.languages) or 'unknown'}",
        "Findings:",
    ]
    for finding in report.findings:
        sections.append(
            f"- {finding.rule_id} [{finding.severity.value}] {finding.title}: {finding.explanation} "
            f"Remediation: {finding.remediation}"
        )
        if finding.file_path and finding.file_path not in selected:
            selected.append(finding.file_path)
    if include_all_files:
        selected = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or any(part.casefold() in _EXCLUDED_DIRECTORIES for part in path.parts):
                continue
            if path.name.casefold() in _EXCLUDED_NAMES or path.suffix.casefold() in _BINARY_SUFFIXES:
                continue
            try:
                path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            selected.append(path.relative_to(root).as_posix())
            if len(selected) >= MAX_FULL_PROJECT_FILES:
                break
        sections.insert(
            2,
            "Review mode: whole project. Inspect every included file, identify cross-file "
            "dependency/configuration/runtime issues, and separate confirmed problems from guesses.",
        )
    else:
        selected = selected[:8]

    remaining = MAX_FULL_PROJECT_CHARS
    for relative in selected:
        path = root / relative
        if not path.is_file() or remaining <= 0:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        content = redact_text(content)[: min(12_000, remaining)]
        sections.append(f"\nFile: {relative}\n```\n{content}\n```")
        remaining -= len(content)
    if include_all_files and len(selected) >= MAX_FULL_PROJECT_FILES:
        sections.append("\n[Context limit reached: additional files were not sent.]")
    return "\n".join(sections), selected


def request_advice(provider_key: str, prompt: str, *, timeout: int = 60) -> str:
    """Request advice from an explicitly selected provider.

    Callers must redact secrets and obtain user consent before invoking this
    function. The deterministic engine never calls it automatically.
    """

    provider = provider_by_key(provider_key)
    if provider is None:
        raise ValueError(f"Unknown AI provider: {provider_key}")
    api_key = os.environ.get(provider.environment_key)
    if not api_key:
        raise ValueError(f"{provider.environment_key} is not configured.")

    if provider.key == "gemini":
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        request = Request(
            provider.endpoint.format(model=provider.model) + f"?key={api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        payload = {
            "model": provider.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Suggest safe, minimal code repairs. Do not invent credentials or destructive commands.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        request = Request(
            provider.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise ValueError(f"{provider.name} request failed: {error}") from error
    if provider.key == "gemini":
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Gemini returned an unexpected response.") from error
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(f"{provider.name} returned an unexpected response.") from error


__all__ = ["AIProvider", "PROVIDERS", "provider_by_key", "request_advice"]
