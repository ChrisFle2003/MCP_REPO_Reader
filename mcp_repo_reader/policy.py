from __future__ import annotations

from pathlib import Path


DEFAULT_MAX_FILE_BYTES = 32_768
DEFAULT_IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

_BLOCKED_SECRET_FILENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "token.json",
    ".pypirc",
    ".npmrc",
    "config.json",
    ".coverage",
}
_BLOCKED_SECRET_SUFFIXES = (
    ".pem",
    ".key",
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".sqlite",
    ".db",
)
_BLOCKED_SECRET_PREFIXES = (".env.", "secrets.", "vault.")
_DOCKER_CONFIG_PARTS = {".docker", "docker"}


def is_ignored_dir(name: str) -> bool:
    return name in DEFAULT_IGNORED_DIRS


def is_blocked_secret_path(relative_path: Path) -> bool:
    name = relative_path.name
    lower_name = name.lower()
    lower_parts = {part.lower() for part in relative_path.parts}

    if lower_name in _BLOCKED_SECRET_FILENAMES:
        return True
    if lower_name.startswith(_BLOCKED_SECRET_PREFIXES):
        return True
    if lower_name.endswith(_BLOCKED_SECRET_SUFFIXES):
        return True
    if lower_name == ".npmrc":
        return True
    if lower_name == "config.json" and lower_parts & _DOCKER_CONFIG_PARTS:
        return True
    return False


def is_binary_bytes(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def should_truncate(size_bytes: int, limit_bytes: int) -> bool:
    return size_bytes > limit_bytes


def build_blocked(reason: str, **details: object) -> dict[str, object]:
    payload: dict[str, object] = {"status": "blocked_by_policy", "reason": reason}
    payload.update(details)
    return payload
