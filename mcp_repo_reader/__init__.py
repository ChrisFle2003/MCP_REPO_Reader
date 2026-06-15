"""Standalone read-only MCP repository reader."""

__all__ = ["RepoReaderMCPServer"]


def __getattr__(name: str):
    if name == "RepoReaderMCPServer":
        from .server import RepoReaderMCPServer

        return RepoReaderMCPServer
    raise AttributeError(name)
