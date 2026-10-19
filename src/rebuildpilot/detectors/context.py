"""Shared immutable input passed to every detector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ProjectFile


@dataclass(frozen=True)
class ScanContext:
    root: Path
    files: tuple[ProjectFile, ...]
    directories: tuple[str, ...]

    def named(self, name: str) -> list[ProjectFile]:
        return [item for item in self.files if Path(item.relative_path).name.lower() == name.lower()]

    def at(self, relative_path: str) -> ProjectFile | None:
        wanted = relative_path.replace("\\", "/").lower()
        return next((item for item in self.files if item.relative_path.lower() == wanted), None)

    def text_files(self) -> tuple[ProjectFile, ...]:
        return tuple(item for item in self.files if item.text is not None)
