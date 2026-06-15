from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .paths import PathPolicyError
from .paths import to_repo_relative
from .policy import DEFAULT_IGNORED_DIRS
from .policy import is_binary_bytes
from .policy import is_blocked_secret_path
from .policy import is_ignored_dir
from .policy import should_truncate
from .redaction import redact_text


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".md": "markdown",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
}
TEXT_EXTENSIONS = set(LANGUAGE_BY_SUFFIX) | {".txt", ".rst", ".ini", ".cfg"}


def build_repo_tree(
    repo_root: Path,
    base_path: Path,
    *,
    max_depth: int,
    max_entries: int,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    truncated = False

    for current_path, dir_names, file_names in walk_repo(repo_root, base_path):
        depth = _relative_depth(base_path, current_path)
        if depth > max_depth:
            dir_names[:] = []
            continue

        if current_path != base_path:
            entries.append({"type": "dir", "path": to_repo_relative(repo_root, current_path)})
            if len(entries) >= max_entries:
                truncated = True
                break

        if depth >= max_depth:
            dir_names[:] = []
            continue

        for file_name in file_names:
            file_path = current_path / file_name
            if _is_blocked_or_unsafe(repo_root, file_path):
                continue
            entries.append(
                {
                    "type": "file",
                    "path": to_repo_relative(repo_root, file_path),
                    "size": file_path.stat().st_size,
                }
            )
            if len(entries) >= max_entries:
                truncated = True
                break
        if truncated:
            break

    return {"status": "ok", "tree": entries, "truncated": truncated}


def read_text_file(repo_root: Path, file_path: Path, *, max_bytes: int) -> dict[str, object]:
    relative = to_repo_relative(repo_root, file_path)
    if is_blocked_secret_path(Path(relative)):
        return _error("BLOCKED_PATH", "Path is blocked by read-only safety policy.", path=relative)

    raw_bytes = file_path.read_bytes()
    if is_binary_bytes(raw_bytes):
        return _error("BINARY_FILE", f"Binary file cannot be returned as text: {relative}", path=relative)

    visible_bytes = raw_bytes[:max_bytes]
    content = redact_text(visible_bytes.decode("utf-8"))
    return {
        "status": "ok",
        "path": relative,
        "content": content,
        "truncated": should_truncate(len(raw_bytes), max_bytes),
        "size": len(raw_bytes),
    }


def search_repo(
    repo_root: Path,
    base_path: Path,
    *,
    query: str,
    max_results: int,
    case_sensitive: bool,
) -> dict[str, object]:
    needle = query if case_sensitive else query.lower()
    results: list[dict[str, object]] = []
    truncated = False

    for file_path in iter_repo_files(repo_root, base_path):
        raw = file_path.read_bytes()
        if is_binary_bytes(raw):
            continue
        text = raw.decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                results.append(
                    {
                        "path": to_repo_relative(repo_root, file_path),
                        "line": line_number,
                        "preview": redact_text(line.strip()),
                    }
                )
                if len(results) >= max_results:
                    truncated = True
                    return {
                        "status": "ok",
                        "query": query,
                        "results": results,
                        "truncated": truncated,
                    }

    return {"status": "ok", "query": query, "results": results, "truncated": truncated}


def summarize_files(
    repo_root: Path,
    target_path: Path,
    *,
    max_depth: int,
    max_files: int,
) -> dict[str, object]:
    files: list[dict[str, object]] = []
    truncated = False

    if target_path.is_file():
        candidates = [target_path]
    else:
        candidates = []
        for file_path in iter_repo_files(repo_root, target_path):
            if _relative_depth(target_path, file_path.parent) > max_depth:
                continue
            candidates.append(file_path)
            if len(candidates) >= max_files:
                truncated = True
                break

    for file_path in candidates[:max_files]:
        files.append(
            {
                "path": to_repo_relative(repo_root, file_path),
                "size": file_path.stat().st_size,
                "kind": guess_file_kind(file_path),
            }
        )

    return {"status": "ok", "files": files, "truncated": truncated}


def build_manifest(repo_root: Path, *, max_depth: int) -> dict[str, object]:
    file_count = 0
    dir_count = 0
    ignored_count = 0

    for current_path, dir_names, file_names in walk_repo(repo_root, repo_root):
        if current_path != repo_root:
            dir_count += 1

        raw_children = [name for name in os.listdir(current_path) if (current_path / name).is_dir()]
        ignored_count += sum(1 for name in raw_children if name in DEFAULT_IGNORED_DIRS)

        for file_name in file_names:
            file_path = current_path / file_name
            if _is_blocked_or_unsafe(repo_root, file_path):
                ignored_count += 1
                continue
            file_count += 1

    return {
        "status": "ok",
        "repo_root_name": repo_root.name,
        "file_count": file_count,
        "dir_count": dir_count,
        "ignored_count": ignored_count,
        "max_depth": max_depth,
        "notices": [],
    }


def count_visible_files(repo_root: Path) -> int:
    return sum(1 for _ in iter_repo_files(repo_root, repo_root))


def iter_repo_files(repo_root: Path, base_path: Path) -> Iterator[Path]:
    for current_path, _, file_names in walk_repo(repo_root, base_path):
        for file_name in file_names:
            file_path = current_path / file_name
            if _is_blocked_or_unsafe(repo_root, file_path):
                continue
            yield file_path


def walk_repo(repo_root: Path, base_path: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    for current_root, dir_names, file_names in os.walk(base_path, followlinks=False):
        current_path = Path(current_root)
        dir_names[:] = sorted(
            name for name in dir_names if not is_ignored_dir(name) and _is_safe_child(repo_root, current_path / name)
        )
        visible_files = [
            name for name in sorted(file_names) if _is_safe_child(repo_root, current_path / name)
        ]
        yield current_path, dir_names, visible_files


def guess_file_kind(file_path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text" if file_path.suffix.lower() in TEXT_EXTENSIONS else "file")


def _is_safe_child(repo_root: Path, path: Path) -> bool:
    try:
        to_repo_relative(repo_root, path.resolve(strict=True))
    except (FileNotFoundError, PathPolicyError):
        return False
    return True


def _is_blocked_or_unsafe(repo_root: Path, file_path: Path) -> bool:
    try:
        relative = Path(to_repo_relative(repo_root, file_path.resolve(strict=True)))
    except (FileNotFoundError, PathPolicyError):
        return True
    return is_blocked_secret_path(relative)


def _relative_depth(base_path: Path, candidate: Path) -> int:
    relative = candidate.relative_to(base_path)
    return len(relative.parts)


def _error(code: str, message: str, **details: object) -> dict[str, object]:
    payload: dict[str, object] = {"status": "error", "error_code": code, "message": message}
    if details:
        payload["details"] = details
    return payload
