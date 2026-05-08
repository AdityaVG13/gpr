"""Stalemate detection: payload-hash + checkbox accounting.

Inspired by francescoalemanno/dex (checkbox accounting) and
mikeyobrien/ralph-orchestrator (payload-hash same-signature counter),
but reimplemented from scratch.

Two independent signals must both indicate no progress for N consecutive
iterations before declaring stalemate. The case-split stall note tells
the model exactly what shape of failure it is showing.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

STALEMATE_THRESHOLD = 4
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<state>[ xX])\]", re.MULTILINE)


def git_diff_hash(repo: str | Path) -> str:
    """Hash of `git diff` output. None-equivalent if not a git repo."""
    try:
        out = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            timeout=30,
            check=False,
        )
        if out.returncode != 0:
            return _file_mtime_hash(repo)
        return hashlib.sha256(out.stdout).hexdigest()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _file_mtime_hash(repo)


def _file_mtime_hash(repo: str | Path) -> str:
    """Fallback for non-git: hash of (path, mtime, size) for tracked-looking files."""
    h = hashlib.sha256()
    repo = Path(repo)
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{rel}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def checkbox_count(spine_md_path: str | Path) -> tuple[int, int]:
    """Return (open, total) checkbox counts in Spine.md."""
    p = Path(spine_md_path)
    if not p.exists():
        return (0, 0)
    text = p.read_text(errors="replace")
    total = 0
    open_count = 0
    for m in CHECKBOX_RE.finditer(text):
        total += 1
        if m.group("state") == " ":
            open_count += 1
    return (open_count, total)


def update_signature(
    plan: dict[str, Any], current_hash: str, current_checkboxes: tuple[int, int]
) -> tuple[bool, dict[str, int]]:
    """Update plan globalState with new signature. Returns (is_stalled, deltas).

    is_stalled is True when both payload hash AND checkbox counts have not
    changed for STALEMATE_THRESHOLD consecutive iterations.
    """
    gs = plan["globalState"]
    last_hash = gs.get("lastPayloadHash")
    last_cb = tuple(gs.get("lastCheckboxCount") or [0, 0])

    same_hash = last_hash == current_hash
    same_checkboxes = last_cb == current_checkboxes

    delta_open = current_checkboxes[0] - last_cb[0]
    delta_total = current_checkboxes[1] - last_cb[1]

    if last_hash is None:
        gs["consecutiveSameSignature"] = 1
    elif same_hash and same_checkboxes:
        gs["consecutiveSameSignature"] = gs.get("consecutiveSameSignature", 1) + 1
    else:
        gs["consecutiveSameSignature"] = 1

    gs["lastPayloadHash"] = current_hash
    gs["lastCheckboxCount"] = list(current_checkboxes)

    return (
        gs["consecutiveSameSignature"] >= STALEMATE_THRESHOLD,
        {
            "delta_open": delta_open,
            "delta_total": delta_total,
            "consecutive_same": gs["consecutiveSameSignature"],
        },
    )


def stall_note(
    made_commits: bool, checkbox_progress: bool, consecutive_same: int
) -> str:
    """Produce a case-split stall note injected into the next prompt.

    The 4 cases give the model precise feedback on the shape of its
    failure mode rather than a generic 'try harder'.
    """
    if not made_commits and not checkbox_progress:
        kind = "no-op"
        note = (
            "Last iteration produced no code changes AND no checkbox progress. "
            "You are not making forward motion. Pick a SMALLER concrete subtask "
            "from the current intent — one file, one function, one test. Do not "
            "describe; commit code."
        )
    elif made_commits and not checkbox_progress:
        kind = "code-without-plan-update"
        note = (
            "Last iteration changed code but did not update the plan or memory. "
            "Reconcile: which Check did your changes satisfy? Update Spine.md to "
            "reflect the new state. If your changes do NOT satisfy any current "
            "Check, you may be working on the wrong thing — re-read the goal."
        )
    elif not made_commits and checkbox_progress:
        kind = "plan-without-code"
        note = (
            "Last iteration marked checkboxes done but did not change any code. "
            "This is the most dangerous failure mode. Revert the checkbox edits "
            "and either (a) actually do the work or (b) emit a 'blocked' signal "
            "with a precise reason."
        )
    else:
        kind = "both-but-no-signature-change"
        note = (
            "Both code and plan changed, but the overall signature is unchanged "
            "vs prior iteration — likely flapping (edit, revert, edit, revert). "
            "Halt and inspect: what's the actual blocker?"
        )
    return (
        f"[stall-recovery — case={kind}, consecutive_same={consecutive_same}]\n{note}"
    )
