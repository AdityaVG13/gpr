"""Secret redaction patterns."""

from __future__ import annotations

from lib.state import redact


def test_github_pat():
    out = redact.redact("my token is ghp_AAAABBBBCCCCDDDDEEEEFFFF1111222233334444")
    assert "ghp_AAAA" not in out
    assert "REDACTED:github-pat" in out


def test_aws_access_key():
    out = redact.redact("creds: AKIAIOSFODNN7EXAMPLE in env")
    assert "AKIA" not in out


def test_anthropic_key():
    out = redact.redact("export ANTHROPIC_API_KEY=sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF1111222233334444AAAABBBBCCCCDDDD")
    assert "sk-ant" not in out


def test_assignment_pattern():
    out = redact.redact("PASSWORD=hunter2hunter2hunter2hunter2")
    assert "hunter2" not in out


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.dyt0CoTl4WoVjAHI9Q_CwSKhl6d_9rhM3NrXuJttkao"
    out = redact.redact(f"auth: {jwt}")
    assert "REDACTED:jwt" in out


def test_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nABCDEF\nGHIJKL\n-----END RSA PRIVATE KEY-----"
    out = redact.redact(pem)
    assert "BEGIN" not in out or "REDACTED" in out


def test_no_false_match_on_normal_text():
    txt = "this is just regular text without any secrets"
    out = redact.redact(txt)
    assert out == txt
