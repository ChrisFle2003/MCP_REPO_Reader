from __future__ import annotations

from pathlib import Path

import pytest

from mcp_repo_reader.paths import PathPolicyError
from mcp_repo_reader.paths import resolve_repo_path


def test_rejects_absolute_path_input(tmp_path: Path) -> None:
    with pytest.raises(PathPolicyError, match="absolute"):
        resolve_repo_path(tmp_path, "/etc/passwd")


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathPolicyError, match="traversal"):
        resolve_repo_path(tmp_path, "../outside.txt")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "escape-link"
    link.symlink_to(outside)

    with pytest.raises(PathPolicyError, match="repository root"):
        resolve_repo_path(tmp_path, "escape-link")


def test_allows_normal_in_repo_file_resolution(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "guide.txt"
    target.parent.mkdir()
    target.write_text("ok", encoding="utf-8")

    resolved = resolve_repo_path(tmp_path, "docs/guide.txt")

    assert resolved == target.resolve()
