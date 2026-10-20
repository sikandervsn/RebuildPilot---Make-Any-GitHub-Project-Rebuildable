"""Project discovery for folders that may contain one or more projects."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .scanner import IGNORED_DIRECTORIES


PROJECT_MARKERS = {
    "cargo.toml",
    "composer.json",
    "gemfile",
    "go.mod",
    "manage.py",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}
SOURCE_SUFFIXES = {".c", ".cpp", ".go", ".java", ".js", ".py", ".rs", ".ts", ".tsx"}
SOURCE_NAMES = {"dockerfile", "makefile"}


@dataclass(frozen=True)
class ProjectCandidate:
    """A directory containing recognizable project content."""

    path: Path
    markers: tuple[str, ...]
    file_count: int

    @property
    def label(self) -> str:
        marker_text = ", ".join(self.markers[:3])
        if len(self.markers) > 3:
            marker_text += ", ..."
        return f"{self.path}  [{marker_text}]"


def discover_projects(root: str | Path) -> list[ProjectCandidate]:
    """Find project roots without descending into generated/dependency folders."""

    workspace = Path(root).expanduser().resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise ValueError(f"Workspace is not a directory: {root}")

    files_by_directory: dict[Path, list[str]] = {}
    for directory, dirnames, filenames in os.walk(workspace, topdown=True):
        dirnames[:] = sorted(
            (name for name in dirnames if name.casefold() not in IGNORED_DIRECTORIES),
            key=str.casefold,
        )
        current = Path(directory)
        files_by_directory[current] = sorted(filenames, key=str.casefold)

    candidates: list[ProjectCandidate] = []
    for directory, filenames in files_by_directory.items():
        lower_names = {name.casefold() for name in filenames}
        markers = sorted(lower_names.intersection(PROJECT_MARKERS))
        source_files = [
            name
            for name in filenames
            if Path(name).suffix.casefold() in SOURCE_SUFFIXES
            or name.casefold() in SOURCE_NAMES
        ]
        if not markers and (not source_files or directory != workspace):
            continue
        candidates.append(
            ProjectCandidate(
                path=directory,
                markers=tuple(markers or ["source files"]),
                file_count=len(filenames),
            )
        )

    return sorted(
        candidates,
        key=lambda item: (
            len(item.path.relative_to(workspace).parts),
            item.path.as_posix().casefold(),
        ),
    )


__all__ = ["ProjectCandidate", "discover_projects"]
