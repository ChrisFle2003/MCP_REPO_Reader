from __future__ import annotations

from pathlib import Path

from mcp_repo_reader.policy import DEFAULT_IGNORED_DIRS
from mcp_repo_reader.policy import DEFAULT_MAX_FILE_BYTES
from mcp_repo_reader.policy import build_blocked
from mcp_repo_reader.policy import is_binary_bytes
from mcp_repo_reader.policy import is_blocked_secret_path
from mcp_repo_reader.policy import is_ignored_dir
from mcp_repo_reader.policy import should_truncate


def test_blocks_env_files() -> None:
    assert is_blocked_secret_path(Path(".env")) is True
    assert is_blocked_secret_path(Path(".env.production")) is True


def test_blocks_private_key_like_files() -> None:
    assert is_blocked_secret_path(Path("keys/id_rsa")) is True
    assert is_blocked_secret_path(Path("tls/server.pem")) is True
    assert is_blocked_secret_path(Path("tls/server.key")) is True


def test_identifies_ignored_directories() -> None:
    assert ".git" in DEFAULT_IGNORED_DIRS
    assert is_ignored_dir(".venv") is True
    assert is_ignored_dir("src") is False


def test_detects_large_file_truncation_policy() -> None:
    assert should_truncate(DEFAULT_MAX_FILE_BYTES + 1, DEFAULT_MAX_FILE_BYTES) is True
    assert should_truncate(DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILE_BYTES) is False


def test_detects_binary_file_policy() -> None:
    assert is_binary_bytes(b"plain text") is False
    assert is_binary_bytes(b"\x00\x01\x02binary") is True


def test_build_blocked_payload_shape() -> None:
    payload = build_blocked("secret_file", path=".env")

    assert payload["status"] == "blocked_by_policy"
    assert payload["reason"] == "secret_file"
    assert payload["path"] == ".env"
