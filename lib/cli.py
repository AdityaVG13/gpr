"""Python dispatcher: state operations the bash CLI shells out to.

Subcommands print machine-readable JSON when --json is given; otherwise
human-readable status. Bash callers parse the JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .state import audit as audit_mod
from .state import budget as budget_mod
from .state import events as events_mod
from .state import plan as plan_mod
from .state import redact as redact_mod
from .state import signal as signal_mod
from .state import stalemate as stalemate_mod
from .state.lock import file_lock


def _project_root() -> Path:
    return Path(os.environ.get("GPR_PROJECT_ROOT", os.getcwd()))


def _gpr_dir() -> Path:
    return _project_root() / ".gpr"


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _detect_branch(root: Path) -> str:
    git_dir = root / ".git"
    if not git_dir.exists():
        return "unknown"
    try:
        head = (git_dir / "HEAD").read_text().strip()
        if head.startswith("ref: refs/heads/"):
            return head[len("ref: refs/heads/"):]
        return head[:8]
    except OSError:
        return "unknown"


def cmd_init(args: argparse.Namespace) -> int:
    root = _project_root()
    if (root / ".gpr" / "Plan.json").exists() and not args.force:
        print(f"error: .gpr/Plan.json already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    project = args.project or root.name
    branch = args.branch or _detect_branch(root)
    plan = plan_mod.empty_plan(project, args.objective, branch)
    if args.from_:
        try:
            extra = json.loads(Path(args.from_).read_text())
            for key in ("intents", "qualityGates", "budget"):
                if key in extra:
                    plan[key] = extra[key]
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: cannot read {args.from_}: {exc}", file=sys.stderr)
            return 1
    if args.force and plan_mod.plan_path(root).exists():
        plan_mod.plan_path(root).unlink()
    plan_mod.init(root, project, args.objective, branch)
    saved = plan_mod.load(root)
    saved["intents"] = plan["intents"]
    saved["qualityGates"] = plan["qualityGates"]
    saved["budget"] = plan["budget"]
    plan_mod.save(root, saved)
    (_gpr_dir() / "Pinned.md").write_text(_pinned_template())
    (_gpr_dir() / "Spine.md").write_text(_spine_template(args.objective))
    (_gpr_dir() / "Steer.md").write_text("")
    (_gpr_dir() / "errors.log").touch()
    if args.json:
        _print_json({"ok": True, "plan": str(plan_mod.plan_path(root))})
    return 0


def _pinned_template() -> str:
    return (
        "# Pinned\n\n"
        "Read-only invariants. The agent is told never to overwrite this file.\n"
        "Add constraints that must hold across every iteration:\n\n"
        "- Examples:\n"
        "  - Tech stack: <e.g. python 3.12, fastapi, sqlite>\n"
        "  - Style: <e.g. all functions typed; no implicit Any>\n"
        "  - Forbidden: <e.g. do not pull in heavy frameworks; no global state>\n"
    )


def _spine_template(goal: str) -> str:
    return (
        "# Spine\n\n"
        "Externalized memory. The agent rewrites or appends to this file as needed.\n"
        "Survives clean-context rounds. Keep it under 10KB.\n\n"
        f"Goal: {goal}\n\n"
        "## Decisions\n\n"
        "## Architecture\n\n"
        "## Open questions\n"
    )


def cmd_status(args: argparse.Namespace) -> int:
    root = _project_root()
    plan = plan_mod.load(root)
    state = budget_mod.load(root)
    bstatus = budget_mod.status(plan, state)
    intents_by_status: dict[str, int] = {}
    for it in plan["intents"]:
        intents_by_status[it["status"]] = intents_by_status.get(it["status"], 0) + 1
    next_intent = plan_mod.select_next_intent(plan)
    payload = {
        "project": plan["project"],
        "goal": plan["goal"],
        "branch": plan["branch"],
        "status": plan.get("status", "pursuing"),
        "intents": intents_by_status,
        "iteration": plan["globalState"]["iteration"],
        "next_intent_id": next_intent["id"] if next_intent else None,
        "next_intent_title": next_intent["title"] if next_intent else None,
        "budget": {
            "tokensInput": state["tokensInput"],
            "tokensOutput": state["tokensOutput"],
            "wallClockSeconds": state["wallClockSeconds"],
            "costUsd": state["costUsd"],
            "fraction_used": bstatus["fraction_used"],
            "binding_axis": bstatus["binding_axis"],
        },
    }
    _print_json(payload)
    return 0


def cmd_next_intent(args: argparse.Namespace) -> int:
    root = _project_root()
    with file_lock(plan_mod.lock_path(root)):
        plan = plan_mod.load(root)
        reset = plan_mod.reset_stale_in_progress(plan, args.stale_seconds)
        # Continue any active in_progress intent before picking a new one.
        nxt = next(
            (it for it in plan["intents"] if it["status"] == "in_progress"), None
        )
        newly_started = False
        if nxt is None:
            nxt = plan_mod.select_next_intent(plan)
            if nxt is None:
                plan_mod.save(root, plan)
                if args.json:
                    _print_json(
                        {
                            "ok": False,
                            "reason": "no_open_intents",
                            "reset": reset,
                            "all_done": plan_mod.all_done(plan),
                        }
                    )
                return 2
            plan_mod.mark_in_progress(plan, nxt["id"])
            newly_started = True
        plan_mod.save(root, plan)
    if args.json:
        _print_json(
            {
                "ok": True,
                "intent": nxt,
                "reset_stale": reset,
                "newly_started": newly_started,
            }
        )
    else:
        print(nxt["id"])
    return 0


def cmd_render_prompt(args: argparse.Namespace) -> int:
    from . import render

    root = _project_root()
    plan = plan_mod.load(root)
    intent_id = args.intent
    if intent_id is None:
        for it in plan["intents"]:
            if it["status"] == "in_progress":
                intent_id = it["id"]
                break
    if intent_id is None:
        print("error: no in-progress intent; pass --intent or run gpr next-intent first", file=sys.stderr)
        return 1
    intent = plan_mod.find_intent(plan, intent_id)
    if intent is None:
        print(f"error: unknown intent {intent_id}", file=sys.stderr)
        return 1
    state = budget_mod.load(root)
    text = render.continuation(plan, intent, state, _gpr_dir())
    sys.stdout.write(text)
    return 0


def cmd_ingest_signal(args: argparse.Namespace) -> int:
    root = _project_root()
    text = sys.stdin.read() if args.stdin else (args.text or "")
    if not text:
        print("error: pass --stdin or --text", file=sys.stderr)
        return 1
    try:
        sig = signal_mod.parse(text)
    except signal_mod.SignalError as exc:
        print(f"error: invalid signal: {exc}", file=sys.stderr)
        return 1
    intent_id = sig.get("intent") or args.intent
    audit_result: dict[str, Any] | None = None

    with file_lock(plan_mod.lock_path(root)):
        plan = plan_mod.load(root)
        gs = plan["globalState"]
        gs["iteration"] = gs.get("iteration", 0) + 1

        if sig["status"] == "done" and intent_id:
            audit_result = audit_mod.audit_intent(plan, intent_id, root)
            if audit_result["all_pass"]:
                proofs = audit_mod.proofs_from_audit(audit_result)
                plan_mod.mark_done(plan, intent_id, proofs)
            else:
                plan_mod.revert_to_open(
                    plan,
                    intent_id,
                    {"reason": "audit_failed", "audit": audit_result},
                )
        elif sig["status"] == "blocked" and intent_id:
            it = plan_mod.find_intent(plan, intent_id)
            if it and it["status"] == "in_progress":
                pass
            gs["consecutiveBlocked"] = gs.get("consecutiveBlocked", 0) + 1
        elif sig["status"] in {"decide", "rescope"}:
            steer = _gpr_dir() / "Steer.md"
            existing = steer.read_text() if steer.exists() else ""
            steer.write_text(
                f"# {sig['status'].capitalize()} from agent — iter {gs['iteration']}\n\n"
                f"{sig['reason']}\n\n---\n{existing}"
            )
        elif sig["status"] == "progress" and intent_id:
            pass

        if sig.get("memory") and not sig.get("_synthetic"):
            _apply_memory(_gpr_dir(), sig["memory"])

        plan_mod.save(root, plan)

    events_mod.emit(
        root,
        "iteration",
        {
            "iteration": plan["globalState"]["iteration"],
            "signal": sig,
            "audit": audit_result,
        },
    )
    if args.json:
        _print_json(
            {
                "ok": True,
                "signal": sig,
                "audit": audit_result,
                "iteration": plan["globalState"]["iteration"],
            }
        )
    return 0


def _apply_memory(gpr_dir: Path, memory: dict[str, Any]) -> None:
    spine = gpr_dir / "Spine.md"
    history = gpr_dir / "main_history"
    history.mkdir(exist_ok=True)
    if spine.exists():
        ts = uuid.uuid4().hex[:8]
        (history / f"Spine-{ts}.md").write_text(spine.read_text())
        existing = history.glob("Spine-*.md")
        files = sorted(existing, key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[3:]:
            old.unlink(missing_ok=True)
    mode = memory.get("mode", "append")
    content = memory.get("content", "")
    if mode == "rewrite":
        spine.write_text(content)
    else:
        if spine.exists():
            spine.write_text(spine.read_text().rstrip() + "\n\n" + content + "\n")
        else:
            spine.write_text(content + "\n")


def _git_diff(root: Path, base_ref: str = "HEAD") -> str:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "diff", base_ref],
            cwd=str(root),
            capture_output=True,
            timeout=20,
            check=False,
        )
        return out.stdout.decode("utf-8", "replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def cmd_render_audit_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod

    root = _project_root()
    plan = plan_mod.load(root)
    intent = plan_mod.find_intent(plan, args.intent)
    if intent is None:
        print(f"error: unknown intent {args.intent}", file=sys.stderr)
        return 1
    audit_path = Path(args.audit_json) if args.audit_json else None
    if audit_path and audit_path.exists():
        try:
            saved = json.loads(audit_path.read_text())
            audit_detail = saved.get("audit", {}).get("details", []) or saved.get("details", [])
        except json.JSONDecodeError:
            audit_detail = []
    else:
        audit_detail = []
    diff = _git_diff(root, args.diff_base)
    text = render_mod.audit_check_prompt(plan, intent, audit_detail, diff, _gpr_dir())
    sys.stdout.write(text)
    return 0


def cmd_ingest_audit_verdict(args: argparse.Namespace) -> int:
    root = _project_root()
    text = sys.stdin.read() if args.stdin else (args.text or "")
    if not text:
        print("error: pass --stdin or --text", file=sys.stderr)
        return 1
    try:
        verdict = signal_mod.parse_audit_verdict(text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if verdict["verdict"] == "fail":
        with file_lock(plan_mod.lock_path(root)):
            plan = plan_mod.load(root)
            intent = plan_mod.find_intent(plan, args.intent)
            if intent and intent["status"] == "done" and verdict["recommend"] == "revert_to_open":
                plan_mod.revert_to_open(
                    plan,
                    args.intent,
                    {"reason": "layer2_audit_failed", "verdict": verdict},
                )
            plan_mod.save(root, plan)

    events_mod.emit(
        root,
        "layer2_audit",
        {"intent": args.intent, "verdict": verdict},
    )
    if args.json:
        _print_json(verdict)
    return 0 if verdict["verdict"] == "pass" else 1


def cmd_render_reverse_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod

    root = _project_root()
    plan = plan_mod.load(root)
    diff = _git_diff(root, args.diff_base)
    text = render_mod.reverse_audit_prompt(plan, diff, _gpr_dir())
    sys.stdout.write(text)
    return 0


def cmd_ingest_reverse_verdict(args: argparse.Namespace) -> int:
    root = _project_root()
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        verdict = signal_mod.parse_reverse_audit(text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rec = verdict["recommendation"]
    if rec == "reopen_intents":
        with file_lock(plan_mod.lock_path(root)):
            plan = plan_mod.load(root)
            for r in verdict["regressions"]:
                intent_id = r.get("intent")
                if intent_id and plan_mod.find_intent(plan, intent_id):
                    plan_mod.revert_to_open(
                        plan,
                        intent_id,
                        {"reason": "reverse_audit_regression", "detail": r},
                    )
            plan_mod.save(root, plan)
    elif rec == "rescope":
        steer = _gpr_dir() / "Steer.md"
        existing = steer.read_text() if steer.exists() else ""
        steer.write_text(
            "# Reverse-audit recommends rescope\n\n"
            f"Goal gaps:\n- " + "\n- ".join(verdict["goal_gaps"])
            + f"\n\n---\n{existing}"
        )
    elif rec == "add_intents":
        steer = _gpr_dir() / "Steer.md"
        existing = steer.read_text() if steer.exists() else ""
        steer.write_text(
            "# Reverse-audit recommends adding intents\n\n"
            f"Goal gaps that need new intents:\n- " + "\n- ".join(verdict["goal_gaps"])
            + f"\n\n---\n{existing}"
        )

    events_mod.emit(root, "reverse_audit", verdict)
    if args.json:
        _print_json(verdict)
    return 0 if verdict["clean"] else 2


def cmd_render_commit_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod
    root = _project_root()
    plan = plan_mod.load(root)
    intent = plan_mod.find_intent(plan, args.intent)
    if intent is None:
        print(f"error: unknown intent {args.intent}", file=sys.stderr)
        return 1
    audit_detail: list[dict[str, Any]] = []
    if args.audit_json and Path(args.audit_json).exists():
        try:
            saved = json.loads(Path(args.audit_json).read_text())
            audit_detail = saved.get("audit", {}).get("details", []) or saved.get("details", [])
        except json.JSONDecodeError:
            pass
    diff = _git_diff(root, args.diff_base)
    sys.stdout.write(render_mod.commit_message_prompt(intent, audit_detail, diff))
    return 0


def cmd_ingest_commit(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        msg = signal_mod.parse_commit_message(text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(msg)
        return 0
    print(msg["title"])
    if msg["body"]:
        print()
        print(msg["body"])
    if args.apply:
        import subprocess
        full = msg["title"] + ("\n\n" + msg["body"] if msg["body"] else "")
        proc = subprocess.run(
            ["git", "commit", "-m", full],
            cwd=str(_project_root()),
        )
        return proc.returncode
    return 0


def cmd_render_pr_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod
    root = _project_root()
    plan = plan_mod.load(root)
    diff = _git_diff(root, args.diff_base)
    events = events_mod.tail(root, n=50)
    sys.stdout.write(render_mod.pr_description_prompt(plan, diff, events))
    return 0


def cmd_ingest_pr(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        pr = signal_mod.parse_pr_description(text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(pr)
        return 0
    print(pr["title"])
    print()
    print(pr["body"])
    if args.output:
        Path(args.output).write_text(
            f"{pr['title']}\n\n{pr['body']}\n"
        )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from . import html_view
    root = _project_root()
    plan = plan_mod.load(root)
    state = budget_mod.load(root)
    out_path = Path(args.output) if args.output else (_gpr_dir() / "Plan.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_view.render(plan, state, _gpr_dir(), root))
    if args.json:
        _print_json({"ok": True, "path": str(out_path)})
    else:
        print(out_path)
    if args.open:
        import shutil
        opener = shutil.which("open") or shutil.which("xdg-open")
        if opener:
            import subprocess
            subprocess.Popen([opener, str(out_path)])
    return 0


def cmd_revert_intent(args: argparse.Namespace) -> int:
    root = _project_root()
    with file_lock(plan_mod.lock_path(root)):
        plan = plan_mod.load(root)
        plan_mod.revert_to_open(plan, args.intent, {"reason": args.reason or "manual_revert"})
        plan_mod.save(root, plan)
    if args.json:
        _print_json({"ok": True, "intent": args.intent})
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    root = _project_root()
    plan = plan_mod.load(root)
    if args.intent:
        result = audit_mod.audit_intent(plan, args.intent, root)
    else:
        results = []
        for it in plan["intents"]:
            if it["status"] == "done":
                results.append(audit_mod.audit_intent(plan, it["id"], root))
        result = {"per_intent": results}
    if args.reverse:
        result["evidence_sweep"] = audit_mod.evidence_sweep(plan, root)
    if args.json:
        _print_json(result)
    return 0 if (args.intent and result.get("all_pass")) else 0


def cmd_steer(args: argparse.Namespace) -> int:
    root = _project_root()
    steer = _gpr_dir() / "Steer.md"
    text = args.message
    if args.abort:
        text = f"abort\n\n{text}" if text else "abort"
    existing = steer.read_text() if steer.exists() else ""
    steer.write_text(
        f"# Human steer — {plan_mod.utc_now()}\n\n{text}\n\n---\n{existing}"
    )
    print(f"wrote {steer}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    root = _project_root()
    plan = plan_mod.load(root)
    warnings = plan_mod.lint(plan)
    if args.json:
        _print_json({"warnings": warnings})
    else:
        for w in warnings:
            print(f"warning: {w}")
    return 0 if not warnings else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    import shutil
    out: dict[str, Any] = {"checks": []}
    rc = 0
    for name, cmd in [
        ("python3", "python3"),
        ("git", "git"),
        ("jq", "jq"),
        ("claude", "claude"),
        ("codex", "codex"),
        ("opencode", "opencode"),
    ]:
        path = shutil.which(cmd)
        out["checks"].append({"name": name, "ok": bool(path), "path": path})
        if name in ("python3", "git") and not path:
            rc = 1
    out["ok"] = rc == 0
    if args.json:
        _print_json(out)
    return rc


def cmd_record_budget(args: argparse.Namespace) -> int:
    """Record token+wall+cost from an iteration. Called by loop.sh."""
    root = _project_root()
    state = budget_mod.load(root)
    budget_mod.add_iteration(
        state,
        agent=args.agent,
        model=args.model,
        tokens_input=args.tokens_input,
        tokens_output=args.tokens_output,
        wall_seconds=args.wall_seconds,
    )
    plan = plan_mod.load(root)
    bstatus = budget_mod.status(plan, state)
    if bstatus["wrap_up"] and not state.get("wrapUpEntered"):
        state["wrapUpEntered"] = True
        plan["globalState"]["wrapUpFlag"] = True
        plan_mod.save(root, plan)
    budget_mod.save(root, state)
    if args.json:
        _print_json(bstatus)
    return 0


def cmd_record_signature(args: argparse.Namespace) -> int:
    """Update payload-hash + checkbox count signature, return stalemate status."""
    root = _project_root()
    plan = plan_mod.load(root)
    h = stalemate_mod.git_diff_hash(root)
    cb = stalemate_mod.checkbox_count(_gpr_dir() / "Spine.md")
    stalled, deltas = stalemate_mod.update_signature(plan, h, cb)
    plan_mod.save(root, plan)
    note: str | None = None
    if stalled:
        made_commits = h != plan["globalState"].get("lastPayloadHash") or False
        cb_progress = deltas["delta_open"] != 0 or deltas["delta_total"] != 0
        note = stalemate_mod.stall_note(
            made_commits, cb_progress, deltas["consecutive_same"]
        )
    if args.json:
        _print_json({"stalled": stalled, "deltas": deltas, "note": note})
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="gpr-state", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--objective", required=True)
    pi.add_argument("--project", default=None)
    pi.add_argument("--branch", default=None)
    pi.add_argument("--from", dest="from_", default=None)
    pi.add_argument("--force", action="store_true")
    pi.add_argument("--json", action="store_true")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("status")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_status)

    pn = sub.add_parser("next-intent")
    pn.add_argument("--json", action="store_true")
    pn.add_argument("--stale-seconds", type=int, default=plan_mod.STALE_SECONDS_DEFAULT)
    pn.set_defaults(func=cmd_next_intent)

    pr = sub.add_parser("render-prompt")
    pr.add_argument("--intent", default=None)
    pr.set_defaults(func=cmd_render_prompt)

    pis = sub.add_parser("ingest-signal")
    pis.add_argument("--stdin", action="store_true")
    pis.add_argument("--text", default=None)
    pis.add_argument("--intent", default=None)
    pis.add_argument("--json", action="store_true")
    pis.set_defaults(func=cmd_ingest_signal)

    prap = sub.add_parser("render-audit-prompt")
    prap.add_argument("--intent", required=True)
    prap.add_argument("--audit-json", default=None,
                      help="Path to a saved audit.json from the iter dir")
    prap.add_argument("--diff-base", default="HEAD")
    prap.set_defaults(func=cmd_render_audit_prompt)

    piav = sub.add_parser("ingest-audit-verdict")
    piav.add_argument("--intent", required=True)
    piav.add_argument("--stdin", action="store_true")
    piav.add_argument("--text", default=None)
    piav.add_argument("--json", action="store_true")
    piav.set_defaults(func=cmd_ingest_audit_verdict)

    prrp = sub.add_parser("render-reverse-prompt")
    prrp.add_argument("--diff-base", default="HEAD")
    prrp.set_defaults(func=cmd_render_reverse_prompt)

    pirv = sub.add_parser("ingest-reverse-verdict")
    pirv.add_argument("--stdin", action="store_true")
    pirv.add_argument("--text", default=None)
    pirv.add_argument("--json", action="store_true")
    pirv.set_defaults(func=cmd_ingest_reverse_verdict)

    pcp = sub.add_parser("render-commit-prompt")
    pcp.add_argument("--intent", required=True)
    pcp.add_argument("--audit-json", default=None)
    pcp.add_argument("--diff-base", default="HEAD")
    pcp.set_defaults(func=cmd_render_commit_prompt)

    pic = sub.add_parser("ingest-commit")
    pic.add_argument("--stdin", action="store_true")
    pic.add_argument("--text", default=None)
    pic.add_argument("--apply", action="store_true",
                     help="Run git commit with the parsed message")
    pic.add_argument("--json", action="store_true")
    pic.set_defaults(func=cmd_ingest_commit)

    pprp = sub.add_parser("render-pr-prompt")
    pprp.add_argument("--diff-base", default="HEAD")
    pprp.set_defaults(func=cmd_render_pr_prompt)

    pipr = sub.add_parser("ingest-pr")
    pipr.add_argument("--stdin", action="store_true")
    pipr.add_argument("--text", default=None)
    pipr.add_argument("--output", default=None,
                      help="Write the PR body to a file")
    pipr.add_argument("--json", action="store_true")
    pipr.set_defaults(func=cmd_ingest_pr)

    prn = sub.add_parser("render")
    prn.add_argument("--output", default=None,
                     help="Output path (default: .gpr/Plan.html)")
    prn.add_argument("--open", action="store_true",
                     help="Open the rendered file in the default browser")
    prn.add_argument("--json", action="store_true")
    prn.set_defaults(func=cmd_render)

    pri = sub.add_parser("revert-intent")
    pri.add_argument("--intent", required=True)
    pri.add_argument("--reason", default=None)
    pri.add_argument("--json", action="store_true")
    pri.set_defaults(func=cmd_revert_intent)

    pa = sub.add_parser("audit")
    pa.add_argument("--intent", default=None)
    pa.add_argument("--reverse", action="store_true")
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_audit)

    pt = sub.add_parser("steer")
    pt.add_argument("--abort", action="store_true")
    pt.add_argument("message", nargs="?", default="")
    pt.set_defaults(func=cmd_steer)

    pl = sub.add_parser("lint")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_lint)

    pd = sub.add_parser("doctor")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_doctor)

    pb = sub.add_parser("record-budget")
    pb.add_argument("--agent", required=True)
    pb.add_argument("--model", default="default")
    pb.add_argument("--tokens-input", type=int, default=0)
    pb.add_argument("--tokens-output", type=int, default=0)
    pb.add_argument("--wall-seconds", type=float, default=0.0)
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(func=cmd_record_budget)

    pg = sub.add_parser("record-signature")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(func=cmd_record_signature)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
