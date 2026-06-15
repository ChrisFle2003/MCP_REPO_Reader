from __future__ import annotations

from mcp_repo_reader.redaction import redact_text


def test_redacts_openai_and_github_tokens() -> None:
    text = "OPENAI_API_KEY=sk-test123\nghp_secret123"

    redacted = redact_text(text)

    assert "sk-test123" not in redacted
    assert "ghp_secret123" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_bearer_tokens() -> None:
    text = "Authorization: Bearer abc.def.ghi"

    redacted = redact_text(text)

    assert "abc.def.ghi" not in redacted


def test_redacts_private_key_blocks() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"

    redacted = redact_text(text)

    assert "BEGIN PRIVATE KEY" not in redacted
    assert "END PRIVATE KEY" not in redacted


def test_preserves_non_secret_text() -> None:
    text = "regular content without credentials"

    assert redact_text(text) == text
