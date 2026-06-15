from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .paths import PathPolicyError
from .paths import resolve_repo_path
from .policy import DEFAULT_IGNORED_DIRS
from .policy import DEFAULT_MAX_FILE_BYTES
from .scanner import build_manifest
from .scanner import build_repo_tree
from .scanner import count_visible_files
from .scanner import read_text_file
from .scanner import search_repo
from .scanner import summarize_files


SERVER_NAME = "repo-reader-mcp"
SERVER_VERSION = "0.1.0"
MCP_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_TREE_ENTRIES = 500
DEFAULT_MAX_SUMMARY_FILES = 100
DEFAULT_MAX_SEARCH_RESULTS = 50
TOOL_SCHEMAS = {
    "repo_health": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "repo_manifest": {
        "type": "object",
        "properties": {
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 12},
        },
        "additionalProperties": False,
    },
    "repo_tree": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 12},
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000},
        },
        "additionalProperties": False,
    },
    "repo_file_summary": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 12},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        "additionalProperties": False,
    },
    "repo_read_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": DEFAULT_MAX_FILE_BYTES},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "repo_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
            "case_sensitive": {"type": "boolean"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


class RepoReaderMCPServer:
    def __init__(self, repo_root: Path | str, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self.repo_root = Path(repo_root).expanduser()
        self.max_file_bytes = max_file_bytes

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})

        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"acknowledged": True}}
        if method == "initialize":
            return self._ok(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                    "instructions": "Read-only repository MCP. No writes, no shell, no secrets.",
                },
            )
        if method == "tools/list":
            return self._ok(request_id, {"tools": [self._tool_schema(name) for name in sorted(TOOL_SCHEMAS)]})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return self._error(request_id, -32602, "invalid tool call parameters")
            return self._ok(request_id, self._call_tool(name, arguments))

        return self._error(request_id, -32601, f"method not found: {method}")

    def handle_http_request(self, request_body: bytes) -> bytes:
        payload = json.loads(request_body.decode("utf-8"))
        response = self.handle(payload)
        return json.dumps(response, ensure_ascii=True).encode("utf-8")

    def protected_resource_metadata(self, base_url: str) -> dict[str, Any]:
        return {
            "resource": f"{base_url}/mcp",
            "authorization_servers": [base_url],
        }

    def authorization_server_metadata(self, base_url: str) -> dict[str, Any]:
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    def run_stdio(self) -> int:
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            response = self.handle(json.loads(raw_line))
            sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        return 0

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self._call_tool_payload(name, arguments)
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True)}],
            "structuredContent": payload,
            "isError": payload.get("status") == "error",
        }

    def _call_tool_payload(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name not in TOOL_SCHEMAS:
                return self._error_payload("UNKNOWN_TOOL", f"Unknown tool: {name}")
            if name == "repo_health":
                return self._repo_health_payload()

            health = self._repo_health_payload()
            if health["status"] != "ok":
                return self._error_payload(
                    str(health["error_code"]),
                    str(health["message"]),
                    details=health.get("details") if isinstance(health.get("details"), dict) else None,
                )
            repo_root = self._require_repo_root()
            if name == "repo_tree":
                base_path = self._resolve_path(
                    repo_root,
                    arguments.get("path", "."),
                    allow_directory=True,
                    allow_file=False,
                )
                max_depth = int(arguments.get("max_depth", DEFAULT_MAX_DEPTH))
                max_entries = int(arguments.get("max_entries", DEFAULT_MAX_TREE_ENTRIES))
                return build_repo_tree(repo_root, base_path, max_depth=max_depth, max_entries=max_entries)
            if name == "repo_read_file":
                file_path = self._resolve_path(
                    repo_root,
                    arguments["path"],
                    allow_directory=False,
                    allow_file=True,
                )
                limit = int(arguments.get("max_bytes", self.max_file_bytes))
                return read_text_file(repo_root, file_path, max_bytes=min(limit, self.max_file_bytes))
            if name == "repo_search":
                base_path = self._resolve_path(
                    repo_root,
                    arguments.get("path", "."),
                    allow_directory=True,
                    allow_file=False,
                )
                return search_repo(
                    repo_root,
                    base_path,
                    query=str(arguments["query"]),
                    max_results=int(arguments.get("max_results", DEFAULT_MAX_SEARCH_RESULTS)),
                    case_sensitive=bool(arguments.get("case_sensitive", False)),
                )
            if name == "repo_file_summary":
                target_path = self._resolve_path(
                    repo_root,
                    arguments.get("path", "."),
                    allow_directory=True,
                    allow_file=True,
                )
                return summarize_files(
                    repo_root,
                    target_path,
                    max_depth=int(arguments.get("max_depth", DEFAULT_MAX_DEPTH)),
                    max_files=int(arguments.get("max_files", DEFAULT_MAX_SUMMARY_FILES)),
                )
            if name == "repo_manifest":
                return build_manifest(repo_root, max_depth=int(arguments.get("max_depth", DEFAULT_MAX_DEPTH)))
        except KeyError as exc:
            missing = str(exc).strip("'")
            return self._error_payload("INVALID_ARGUMENTS", f"Missing required argument: {missing}")
        except PathPolicyError as exc:
            return self._error_payload("INVALID_PATH", str(exc))
        except FileNotFoundError:
            return self._error_payload("FILE_NOT_FOUND", "Requested path was not found.")
        except PermissionError:
            return self._error_payload("PERMISSION_DENIED", "Requested path is not readable.")
        except UnicodeDecodeError:
            return self._error_payload("BINARY_FILE", "Binary file cannot be returned as text.")
        except OSError as exc:
            return self._error_payload("IO_ERROR", str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self._error_payload(
                "INTERNAL_ERROR",
                "Unhandled tool exception.",
                details={"type": exc.__class__.__name__, "message": str(exc)},
            )

        return self._error_payload("UNKNOWN_TOOL", f"Unknown tool: {name}")

    def _resolve_path(self, repo_root: Path, raw_path: object, *, allow_directory: bool, allow_file: bool) -> Path:
        if not isinstance(raw_path, str):
            raise PathPolicyError("path must be a string")
        return resolve_repo_path(
            repo_root,
            raw_path,
            must_exist=True,
            allow_directory=allow_directory,
            allow_file=allow_file,
        )

    def _tool_schema(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "description": f"Read-only tool: {name}",
            "inputSchema": TOOL_SCHEMAS[name],
        }

    def _ok(self, request_id: object, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: object, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _repo_health_payload(self) -> dict[str, object]:
        repo_root_exists = self.repo_root.exists()
        repo_root_is_dir = self.repo_root.is_dir()
        readable = os.access(self.repo_root, os.R_OK) if repo_root_exists else False
        payload: dict[str, object] = {
            "status": "ok" if repo_root_exists and repo_root_is_dir and readable else "error",
            "repo_root": str(self.repo_root),
            "repo_root_exists": repo_root_exists,
            "repo_root_is_dir": repo_root_is_dir,
            "readable": readable,
            "tools": sorted(TOOL_SCHEMAS),
            "version": SERVER_VERSION,
            "allow_write": False,
            "shell_execution": False,
        }
        if payload["status"] == "error":
            payload["error_code"] = "REPO_ROOT_MISSING" if not repo_root_exists else "REPO_ROOT_INVALID"
            payload["message"] = "Configured repository root is not available." if not repo_root_exists else (
                "Configured repository root is not a readable directory."
            )
            payload["details"] = {"ignored_dirs": sorted(DEFAULT_IGNORED_DIRS)}
        return payload

    def _require_repo_root(self) -> Path:
        health = self._repo_health_payload()
        if health["status"] != "ok":
            raise PathPolicyError(str(health["message"]))
        return self.repo_root.resolve(strict=True)

    def _error_payload(self, code: str, message: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
        payload: dict[str, object] = {"status": "error", "error_code": code, "message": message}
        if details:
            payload["details"] = details
        return payload


class RepoReaderHTTPRequestHandler(BaseHTTPRequestHandler):
    server: "RepoReaderHTTPServer"

    def do_GET(self) -> None:  # noqa: N802
        base_url = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        if self.path == "/health":
            payload = json.dumps({"status": "ok", "server": SERVER_NAME}, ensure_ascii=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/.well-known/oauth-protected-resource/mcp":
            payload = json.dumps(
                self.server.repo_reader.protected_resource_metadata(base_url),
                ensure_ascii=True,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/.well-known/oauth-authorization-server":
            payload = json.dumps(
                self.server.repo_reader.authorization_server_metadata(base_url),
                ensure_ascii=True,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = self.server.repo_reader.handle_http_request(body)
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class RepoReaderHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], repo_root: Path, max_file_bytes: int) -> None:
        super().__init__(server_address, RepoReaderHTTPRequestHandler)
        self.repo_reader = RepoReaderMCPServer(repo_root=repo_root, max_file_bytes=max_file_bytes)


def create_http_server(host: str, port: int, repo_root: Path | str, *, max_file_bytes: int) -> RepoReaderHTTPServer:
    return RepoReaderHTTPServer((host, port), Path(repo_root), max_file_bytes)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone read-only MCP repository reader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--transport", choices=("http", "stdio"), default="http")
    parser.add_argument("--debug-health", action="store_true")
    return parser.parse_args(argv)


def determine_repo_root(cli_repo_root: str | None) -> Path:
    if cli_repo_root:
        return Path(cli_repo_root).expanduser()
    env_repo_root = os.environ.get("REPO_ROOT")
    if env_repo_root:
        return Path(env_repo_root).expanduser()
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = determine_repo_root(args.repo_root)
    server_app = RepoReaderMCPServer(repo_root=repo_root, max_file_bytes=args.max_file_bytes)

    if args.debug_health:
        payload = server_app._repo_health_payload()
        if payload["status"] == "ok":
            payload["visible_file_count"] = count_visible_files(repo_root.resolve(strict=True))
            payload["json_serializable"] = True
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    if args.transport == "stdio":
        return server_app.run_stdio()

    server = create_http_server(args.host, args.port, repo_root, max_file_bytes=args.max_file_bytes)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
