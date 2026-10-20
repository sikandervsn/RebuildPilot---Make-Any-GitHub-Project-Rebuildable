"""Shared immutable input passed to every detector."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from ..models import ProjectFile


@dataclass(frozen=True)
class ScanContext:
    root: Path
    files: tuple[ProjectFile, ...]
    directories: tuple[str, ...]

    @cached_property
    def _by_name(self) -> dict[str, tuple[ProjectFile, ...]]:
        grouped: dict[str, list[ProjectFile]] = {}
        for item in self.files:
            grouped.setdefault(Path(item.relative_path).name.casefold(), []).append(item)
        return {name: tuple(items) for name, items in grouped.items()}

    @cached_property
    def _text_files(self) -> tuple[ProjectFile, ...]:
        return tuple(item for item in self.files if item.text is not None)

    def named(self, name: str) -> list[ProjectFile]:
        return list(self._by_name.get(name.casefold(), ()))

    def at(self, relative_path: str) -> ProjectFile | None:
        wanted = relative_path.replace("\\", "/").lower()
        return next((item for item in self.files if item.relative_path.lower() == wanted), None)

    def text_files(self) -> tuple[ProjectFile, ...]:
        return self._text_files
