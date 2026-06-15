from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_repo_reader.server import RepoReaderMCPServer


def main() -> int:
    parser = argparse.ArgumentParser(description="Local smoke test for the VM001 read-only MCP server")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    server = RepoReaderMCPServer(repo_root=Path(args.repo_root))
    tool_calls = [
        ("repo_health", {}),
        ("repo_manifest", {}),
        ("repo_tree", {}),
        ("repo_file_summary", {"path": "."}),
    ]

    readme = Path(args.repo_root) / "README.md"
    if readme.exists():
        tool_calls.append(("repo_read_file", {"path": "README.md", "max_bytes": 20000}))
        tool_calls.append(("repo_search", {"query": "README", "max_results": 10}))
    else:
        tool_calls.append(("repo_search", {"query": "repo", "max_results": 10}))

    for name, arguments in tool_calls:
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": name,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        print(f"== {name} ==")
        print(json.dumps(response["result"]["structuredContent"], ensure_ascii=True, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
