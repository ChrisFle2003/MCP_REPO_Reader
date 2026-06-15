from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repo_reader_files_exist_at_actual_repo_root() -> None:
    assert (ROOT / "pyproject.toml").exists()
    assert (ROOT / "mcp_repo_reader" / "server.py").exists()
    assert (ROOT / "scripts" / "run_repo_mcp.py").exists()
    assert (ROOT / "docs" / "CUSTOM_MCP_REPO_READER.md").exists()
