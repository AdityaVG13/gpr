"""Best-effort secret redactor for errors.log and other agent-fed text.

This is intentionally conservative: false positives are fine; false
negatives are bad. Document `.gpr/` as gitignored regardless.
"""

from __future__ import annotations

import re

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-access-key]"),
    (
        re.compile(r"\baws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}", re.IGNORECASE),
        "aws_secret_access_key=[REDACTED]",
    ),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "[REDACTED:github-pat]"),
    (re.compile(r"ghs_[A-Za-z0-9]{36}"), "[REDACTED:github-server-token]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{82}"), "[REDACTED:github-fine-grained-pat]"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-]{60,}"), "[REDACTED:anthropic-key]"),
    (re.compile(r"sk-proj-[A-Za-z0-9\-]{20,}"), "[REDACTED:openai-project-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{40,}"), "[REDACTED:llm-key]"),
    (re.compile(r"xoxb-[0-9]+-[0-9]+-[0-9]+-[A-Za-z0-9]+"), "[REDACTED:slack-bot]"),
    (re.compile(r"xoxp-[0-9]+-[0-9]+-[0-9]+-[A-Za-z0-9]+"), "[REDACTED:slack-user]"),
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"),
     "[REDACTED:private-key-block]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b"),
     "[REDACTED:jwt]"),
    (
        re.compile(
            r"(?i)\b(api[_\-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9_\-+/=]{16,})['\"]?"
        ),
        r"\1=[REDACTED]",
    ),
]


def redact(text: str) -> str:
    out = text
    for pattern, repl in PATTERNS:
        out = pattern.sub(repl, out)
    return out
