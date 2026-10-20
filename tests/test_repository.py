from pathlib import Path

import pytest

from rebuildpilot.repository import commit_repository, validate_repository_url


def test_validate_repository_url_accepts_github_https_and_ssh() -> None:
    assert validate_repository_url("https://github.com/example/project.git") == "https://github.com/example/project.git"
    assert validate_repository_url("git@github.com:example/project.git") == "git@github.com:example/project.git"


@pytest.mark.parametrize(
    "value",
    ["https://gitlab.com/example/project.git", "https://github.com/example", "file:///tmp/project", ""],
)
def test_validate_repository_url_rejects_unsupported_sources(value: str) -> None:
    with pytest.raises(ValueError):
        validate_repository_url(value)


def test_commit_repository_rejects_empty_message(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        commit_repository(tmp_path, " ")
