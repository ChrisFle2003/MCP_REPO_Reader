from __future__ import annotations

from pathlib import Path


class PathPolicyError(ValueError):
    """Raised when a requested path violates repository containment rules."""


def resolve_repo_path(
    repo_root: Path | str,
    user_path: str,
    *,
    must_exist: bool = True,
    allow_directory: bool = True,
    allow_file: bool = True,
) -> Path:
    root = Path(repo_root).resolve(strict=True)
    candidate = Path(user_path)

    if candidate.is_absolute():
        raise PathPolicyError("absolute paths are not allowed")
    if any(part == ".." for part in candidate.parts):
        raise PathPolicyError("path traversal is not allowed")

    combined = root / candidate
    try:
        resolved = combined.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathPolicyError("path does not exist within repository root") from exc

    _ensure_within_root(root, resolved)

    if must_exist:
        if resolved.is_dir() and not allow_directory:
            raise PathPolicyError("directory path is not allowed")
        if resolved.is_file() and not allow_file:
            raise PathPolicyError("file path is not allowed")

    return resolved


def to_repo_relative(repo_root: Path | str, resolved_path: Path | str) -> str:
    root = Path(repo_root).resolve(strict=True)
    resolved = Path(resolved_path).resolve(strict=True)
    _ensure_within_root(root, resolved)
    relative = resolved.relative_to(root)
    return "." if not relative.parts else relative.as_posix()


def _ensure_within_root(root: Path, resolved: Path) -> None:
    if resolved != root and root not in resolved.parents:
        raise PathPolicyError("path escapes repository root")
