from __future__ import annotations

import re


PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"ghp_[A-Za-z0-9_]+"),
    re.compile(r"xoxb-[A-Za-z0-9-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
]
ASSIGNMENT_RE = re.compile(
    r"(?im)\b(openai_api_key|api[_-]?key|token|secret|password)\b\s*[:=]\s*([^\s\"']+|\"[^\"]*\"|'[^']*')"
)


def contains_private_key_block(text: str) -> bool:
    return bool(PRIVATE_KEY_BLOCK_RE.search(text))


def redact_text(text: str) -> str:
    redacted = PRIVATE_KEY_BLOCK_RE.sub("[REDACTED]", text)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted
