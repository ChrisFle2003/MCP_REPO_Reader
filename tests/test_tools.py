from __future__ import annotations

import json
import os
import threading
import tempfile
from pathlib import Path
from urllib.request import urlopen

from mcp_repo_reader.server import RepoReaderMCPServer
from mcp_repo_reader.server import create_http_server
from mcp_repo_reader.server import determine_repo_root


def call_tool(server: RepoReaderMCPServer, name: str, arguments: dict[str, object]) -> dict[str, object]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    return response["result"]


def extract_structured_content(call_result: dict[str, object]) -> dict[str, object]:
    return call_result["structuredContent"]


def test_initialize_and_tools_list_expose_repo_reader_contract(tmp_path: Path) -> None:
    server = RepoReaderMCPServer(repo_root=tmp_path)

    initialize = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialize["result"]["serverInfo"]["name"] == "repo-reader-mcp"
    assert initialize["result"]["protocolVersion"] == "2025-03-26"

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tool_map = {tool["name"]: tool for tool in listed["result"]["tools"]}
    tool_names = set(tool_map)
    assert tool_names == {
        "repo_health",
        "repo_tree",
        "repo_read_file",
        "repo_search",
        "repo_file_summary",
        "repo_manifest",
    }
    assert tool_map["repo_read_file"]["inputSchema"]["required"] == ["path"]
    assert "query" in tool_map["repo_search"]["inputSchema"]["required"]


def test_repo_health_returns_read_only_metadata(tmp_path: Path) -> None:
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_health", {}))

    assert response["status"] == "ok"
    assert response["allow_write"] is False
    assert response["shell_execution"] is False
    assert response["repo_root_exists"] is True
    assert response["repo_root_is_dir"] is True
    assert response["repo_root"].endswith(tmp_path.name)


def test_repo_tree_ignores_standard_directories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_tree", {"path": ".", "max_depth": 2}))
    paths = {entry["path"] for entry in response["tree"]}

    assert ".git" not in paths
    assert "node_modules" not in paths
    assert ".venv" not in paths
    assert "src" in paths
    assert "src/main.py" in paths


def test_repo_read_file_returns_redacted_text(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("token sk-secret123", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "README.md"}))

    assert response["status"] == "ok"
    assert response["path"] == "README.md"
    assert response["truncated"] is False
    assert "sk-secret123" not in response["content"]
    assert "[REDACTED]" in response["content"]


def test_repo_read_file_blocks_secret_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": ".env"}))

    assert response["status"] == "error"
    assert response["error_code"] == "BLOCKED_PATH"


def test_repo_read_file_truncates_large_files(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    target.write_text("a" * 64, encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path, max_file_bytes=16)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "large.txt"}))

    assert response["truncated"] is True
    assert len(response["content"]) <= 16


def test_repo_read_file_blocks_binary_files(tmp_path: Path) -> None:
    target = tmp_path / "image.dat"
    target.write_bytes(b"\x00\x01\x02")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "image.dat"}))

    assert response["status"] == "error"
    assert response["error_code"] == "BINARY_FILE"


def test_repo_search_finds_matches_and_redacts_excerpts(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("API = 'sk-secret123'\n\ndef target_function():\n    return API\n", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_search", {"query": "target_function"}))

    assert response["status"] == "ok"
    assert response["results"][0]["path"] == "app.py"
    assert response["results"][0]["line"] == 3
    assert "target_function" in response["results"][0]["preview"]

    redacted = extract_structured_content(call_tool(server, "repo_search", {"query": "sk-secret123"}))
    assert redacted["results"]
    assert "sk-secret123" not in redacted["results"][0]["preview"]


def test_repo_file_summary_extracts_key_static_elements(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("# Demo", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_file_summary", {"path": "."}))

    assert response["status"] == "ok"
    assert response["files"][0]["path"] == "README.md"
    assert response["files"][0]["kind"] == "markdown"


def test_repo_manifest_reports_docs_tests_and_entrypoints(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "main.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_manifest", {}))

    assert response["status"] == "ok"
    assert response["repo_root_name"] == tmp_path.name
    assert response["file_count"] >= 2
    assert response["dir_count"] >= 2


def test_http_handler_processes_mcp_requests(tmp_path: Path) -> None:
    server = RepoReaderMCPServer(repo_root=tmp_path)
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")

    payload = server.handle_http_request(request)

    data = json.loads(payload.decode("utf-8"))
    assert data["result"]["serverInfo"]["name"] == "repo-reader-mcp"


def test_tools_call_returns_mcp_call_tool_result(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    result = call_tool(server, "repo_read_file", {"path": "README.md"})

    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert result["structuredContent"]["path"] == "README.md"


def test_http_server_exposes_local_oauth_discovery_stubs(tmp_path: Path) -> None:
    server = create_http_server("127.0.0.1", 0, tmp_path, max_file_bytes=4096)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with urlopen(f"http://{host}:{port}/.well-known/oauth-protected-resource/mcp") as response:
            protected_resource = json.loads(response.read().decode("utf-8"))

        with urlopen(f"http://{host}:{port}/.well-known/oauth-authorization-server") as response:
            authorization_server = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert protected_resource == {
        "resource": f"http://{host}:{port}/mcp",
        "authorization_servers": [f"http://{host}:{port}"],
    }
    assert authorization_server == {
        "issuer": f"http://{host}:{port}",
        "authorization_endpoint": f"http://{host}:{port}/authorize",
        "token_endpoint": f"http://{host}:{port}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


def test_determine_repo_root_prefers_environment_variable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.chdir("/")

    resolved = determine_repo_root(None)

    assert resolved == tmp_path.resolve()


def test_repo_health_does_not_crash_when_repo_root_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing-root"
    server = RepoReaderMCPServer(repo_root=missing)

    response = extract_structured_content(call_tool(server, "repo_health", {}))

    assert response["status"] == "error"
    assert response["error_code"] == "REPO_ROOT_MISSING"


def test_repo_tree_returns_relative_paths_only(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_tree", {}))

    assert all(not str(entry["path"]).startswith("/") for entry in response["tree"])


def test_repo_read_file_blocks_parent_traversal(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "../secret.txt"}))

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_PATH"


def test_repo_read_file_blocks_absolute_paths(tmp_path: Path) -> None:
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "/etc/passwd"}))

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_PATH"


def test_repo_read_file_handles_unicode_decode_error_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "bad.txt"
    target.write_bytes(b"\x80\x81\x82")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_read_file", {"path": "bad.txt"}))

    assert response["status"] == "error"
    assert response["error_code"] == "BINARY_FILE"


def test_repo_search_handles_empty_results_without_crashing(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    response = extract_structured_content(call_tool(server, "repo_search", {"query": "missing"}))

    assert response["status"] == "ok"
    assert response["results"] == []


def test_all_tool_payloads_are_json_serializable(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    tool_calls = [
        ("repo_health", {}),
        ("repo_manifest", {}),
        ("repo_tree", {}),
        ("repo_file_summary", {"path": "."}),
        ("repo_read_file", {"path": "README.md"}),
        ("repo_search", {"query": "Demo"}),
    ]

    for name, arguments in tool_calls:
        result = call_tool(server, name, arguments)
        json.dumps(result)


def test_unknown_tool_and_missing_args_are_returned_as_error_results(tmp_path: Path) -> None:
    server = RepoReaderMCPServer(repo_root=tmp_path)

    unknown = extract_structured_content(call_tool(server, "missing_tool", {}))
    missing_args = extract_structured_content(call_tool(server, "repo_read_file", {}))

    assert unknown["status"] == "error"
    assert unknown["error_code"] == "UNKNOWN_TOOL"
    assert missing_args["status"] == "error"
    assert missing_args["error_code"] == "INVALID_ARGUMENTS"


def test_local_smoke_all_tools_once(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    server = RepoReaderMCPServer(repo_root=tmp_path)

    tool_calls = [
        ("repo_health", {}),
        ("repo_manifest", {}),
        ("repo_tree", {}),
        ("repo_file_summary", {"path": "."}),
        ("repo_read_file", {"path": "README.md"}),
        ("repo_search", {"query": "/home/USER/PROJECT"}),
    ]

    for name, arguments in tool_calls:
        result = call_tool(server, name, arguments)
        assert "structuredContent" in result
        assert "content" in result
