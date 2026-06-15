# Custom MCP Repo Reader

Standalone, read-only MCP server for inspecting a repository safely. It exposes tools for health checks, tree browsing, file summaries, file reads, searches, and repository manifests without allowing writes, shell execution, or path escape outside `REPO_ROOT`.

## Features

- Read-only repository inspection over MCP
- Safe path resolution constrained to `REPO_ROOT`
- Directory tree, file summary, search, and manifest tools
- Text redaction for common secret patterns
- HTTP and `stdio` transports

## Project Status

Stable local utility. The server is intentionally narrow in scope and designed for inspection only.

## Installation

Requires Python 3.11 or newer.

```bash
git clone <repo-url>
cd <repo-name>
python3 -m pip install -e .[test]
```

## Usage

Set the repository root explicitly when starting the server:

```bash
export REPO_ROOT=/path/to/repository
repo-mcp --host 127.0.0.1 --port 8765 --transport http
```

You can also run the module directly:

```bash
export REPO_ROOT=/path/to/repository
python3 -m mcp_repo_reader.server --host 127.0.0.1 --port 8765 --transport http
```

For local MCP clients, use `stdio`:

```bash
export REPO_ROOT=/path/to/repository
python3 -m mcp_repo_reader.server --transport stdio
```

## Tests

```bash
pytest
```

## Repository Layout

- `mcp_repo_reader/` - server implementation, path policy, scanner, and redaction helpers
- `scripts/` - local runner and smoke test helpers
- `tests/` - unit and integration tests
- `docs/` - additional usage notes

## Safety Notes

- Absolute paths are rejected
- `..` traversal is rejected
- Symlink escapes outside `REPO_ROOT` are rejected
- Known secret-like files are blocked
- Common secret tokens are redacted from text output

## Secure MCP Tunnels

If you want to connect a private MCP server to supported OpenAI products without exposing it to the public internet, see the official OpenAI guide for Secure MCP Tunnels:

- [Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

## License

No license file is included yet. Add one before publishing publicly if you want to define reuse terms.
