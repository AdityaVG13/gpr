"""Adapter registry: resolution order + synthetic-passthrough fallback."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _bash_resolve(name: str, env: dict[str, str] | None = None) -> dict:
    """Source agents.sh in a subshell and call _agent_resolve_adapter <name>."""
    cmd = [
        "bash",
        "-c",
        f'source "{REPO}/lib/agents.sh"; _agent_resolve_adapter "{name}"',
    ]
    e = os.environ.copy()
    e["GPR_LIB"] = str(REPO / "lib")
    if env:
        e.update(env)
    r = subprocess.run(cmd, capture_output=True, env=e, check=False, text=True)
    if r.returncode != 0:
        return {}
    return json.loads(r.stdout)


def test_builtin_claude_adapter():
    a = _bash_resolve("claude")
    assert a["cmd"] == "claude"
    assert a["stream_format"] == "claude_stream_json"
    assert "--print" in a["args"]


def test_builtin_codex_adapter():
    a = _bash_resolve("codex")
    assert a["cmd"] == "codex"
    assert a["stream_format"] == "codex_json"


def test_unknown_binary_returns_empty():
    # A name that's neither a built-in adapter nor a binary on PATH.
    a = _bash_resolve("this-binary-definitely-does-not-exist-12345")
    assert a == {}


def test_unknown_binary_on_path_gets_passthrough(tmp_project):
    """A binary present on PATH but with no adapter falls back to stdin-passthrough."""
    fake_bin = tmp_project / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "fake-llm-tool"
    fake.write_text("#!/usr/bin/env bash\ncat\n")
    fake.chmod(0o755)
    env = {"PATH": f"{fake_bin}:" + os.environ.get("PATH", "")}
    a = _bash_resolve("fake-llm-tool", env=env)
    assert a["cmd"] == "fake-llm-tool"
    assert a["prompt"] == "stdin"
    assert a["stream_format"] == "passthrough"


def test_project_adapter_overrides_builtin(tmp_project):
    """A .gpr/agents/claude.json shadows the built-in."""
    target = tmp_project / ".gpr" / "agents"
    target.mkdir(parents=True)
    override = {
        "name": "claude",
        "cmd": "claude-override",
        "args": [],
        "prompt": "stdin",
        "prompt_flag": None,
        "model_flag": None,
        "model_id_default": "override",
        "stream_format": "passthrough",
        "non_interactive_flags": [],
        "timeout_seconds": 60,
    }
    (target / "claude.json").write_text(json.dumps(override))
    env = {"GPR_PROJECT_ROOT": str(tmp_project)}
    a = _bash_resolve("claude", env=env)
    assert a["cmd"] == "claude-override"


def test_custom_adapter_from_env():
    a = _bash_resolve(
        "custom",
        env={
            "GPR_AGENT_CUSTOM_CMD": "ollama run llama3",
            "GPR_AGENT_CUSTOM_PROMPT_MODE": "stdin",
        },
    )
    assert a["cmd"] == "ollama"
    assert a["args"] == ["run", "llama3"]
    assert a["prompt"] == "stdin"


def test_agent_supports_accepts_anything():
    """The allow-list is gone: agent_supports always returns 0."""
    cmd = [
        "bash",
        "-c",
        f'source "{REPO}/lib/agents.sh"; agent_supports "grok" && echo yes || echo no',
    ]
    e = os.environ.copy()
    e["GPR_LIB"] = str(REPO / "lib")
    r = subprocess.run(cmd, capture_output=True, env=e, check=False, text=True)
    assert r.stdout.strip() == "yes"
