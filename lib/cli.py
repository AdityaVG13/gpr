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
from .state import channels as channels_mod
from .state import events as events_mod
from .state import plan as plan_mod
from .state import redact as redact_mod
from .state import signal as signal_mod
from .state import stalemate as stalemate_mod
from .state.lock import file_lock


def _project_root() -> Path:
    return Path(os.environ.get("GPR_PROJECT_ROOT", os.getcwd()))


def _slug_from_args(args: argparse.Namespace | None) -> str:
    """Resolve the active plan slug: --plan flag > $GPR_PLAN > .gpr/active > default."""
    if args is not None and getattr(args, "plan", None):
        return plan_mod.slugify(args.plan)
    env = os.environ.get("GPR_PLAN")
    if env:
        return plan_mod.slugify(env)
    root = _project_root()
    plan_mod.ensure_migration(root)
    active = plan_mod.read_active_slug(root)
    if active:
        return active
    return plan_mod.DEFAULT_SLUG


def _gpr_dir(args: argparse.Namespace | None = None) -> Path:
    """Return the per-plan directory (.gpr/plans/<slug>/)."""
    root = _project_root()
    plan_mod.ensure_migration(root)
    slug = _slug_from_args(args)
    return plan_mod.plan_dir(root, slug)


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
    plan_mod.ensure_migration(root)
    slug = _slug_from_args(args)
    if plan_mod.plan_path(root, slug).exists() and not args.force:
        print(
            f"error: {plan_mod.plan_path(root, slug)} already exists. "
            "Use --force to overwrite, --plan to pick a different slug, "
            "or `gpr import` to fold an external Plan into this project.",
            file=sys.stderr,
        )
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
    if args.force and plan_mod.plan_path(root, slug).exists():
        plan_mod.plan_path(root, slug).unlink()
    plan_mod.init(root, project, args.objective, branch, slug)
    saved = plan_mod.load(root, slug)
    saved["intents"] = plan["intents"]
    saved["qualityGates"] = plan["qualityGates"]
    saved["budget"] = plan["budget"]
    plan_mod.save(root, saved, slug)
    pdir = plan_mod.plan_dir(root, slug)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "Pinned.md").write_text(_pinned_template())
    (pdir / "Spine.md").write_text(_spine_template(args.objective))
    (pdir / "Steer.md").write_text("")
    (pdir / "errors.log").touch()
    # First plan in a fresh project → mark it active.
    if plan_mod.read_active_slug(root) is None:
        plan_mod.write_active_slug(root, slug)
    if args.json:
        _print_json(
            {"ok": True, "plan": str(plan_mod.plan_path(root, slug)), "slug": slug}
        )
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
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
    state = budget_mod.load(root, slug)
    bstatus = budget_mod.status(plan, state)
    intents_by_status: dict[str, int] = {}
    for it in plan["intents"]:
        intents_by_status[it["status"]] = intents_by_status.get(it["status"], 0) + 1
    next_intent = plan_mod.select_next_intent(plan)
    payload = {
        "plan_slug": slug,
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
    slug = _slug_from_args(args)
    with file_lock(plan_mod.lock_path(root, slug)):
        plan = plan_mod.load(root, slug)
        reset = plan_mod.reset_stale_in_progress(plan, args.stale_seconds)
        # Continue any active in_progress intent before picking a new one.
        nxt = next(
            (it for it in plan["intents"] if it["status"] == "in_progress"), None
        )
        newly_started = False
        if nxt is None:
            nxt = plan_mod.select_next_intent(plan)
            if nxt is None:
                plan_mod.save(root, plan, slug)
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
        plan_mod.save(root, plan, slug)
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
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
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
    state = budget_mod.load(root, slug)
    text = render.continuation(plan, intent, state, plan_mod.plan_dir(root, slug))
    sys.stdout.write(text)
    return 0


def cmd_ingest_signal(args: argparse.Namespace) -> int:
    root = _project_root()
    slug = _slug_from_args(args)
    pdir = plan_mod.plan_dir(root, slug)
    text = sys.stdin.read() if args.stdin else (args.text or "")
    if not text:
        print("error: pass --stdin or --text", file=sys.stderr)
        return 1
    try:
        sig = channels_mod.parse("signal", text)
    except signal_mod.SignalError as exc:
        print(f"error: invalid signal: {exc}", file=sys.stderr)
        return 1
    intent_id = sig.get("intent") or args.intent
    audit_result: dict[str, Any] | None = None

    with file_lock(plan_mod.lock_path(root, slug)):
        plan = plan_mod.load(root, slug)
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
            steer = pdir / "Steer.md"
            existing = steer.read_text() if steer.exists() else ""
            steer.write_text(
                f"# {sig['status'].capitalize()} from agent — iter {gs['iteration']}\n\n"
                f"{sig['reason']}\n\n---\n{existing}"
            )
        elif sig["status"] == "progress" and intent_id:
            pass

        if sig.get("memory") and not sig.get("_synthetic"):
            _apply_memory(pdir, sig["memory"])

        plan_mod.save(root, plan, slug)

    events_mod.emit(
        root,
        "iteration",
        {
            "iteration": plan["globalState"]["iteration"],
            "signal": sig,
            "audit": audit_result,
        },
        slug=slug,
    )
    # Save a Plan snapshot under .gpr/plans/<slug>/snapshots/iter-NNNN.json
    # so the HTML viewer's diff overlay has something to compare against.
    snap_dir = pdir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"iter-{plan['globalState']['iteration']:04d}.json"
    snap_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    latest = snap_dir / "latest.json"
    latest.write_text(snap_path.read_text())
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


def _apply_memory(plan_dir_path: Path, memory: dict[str, Any]) -> None:
    spine = plan_dir_path / "Spine.md"
    history = plan_dir_path / "main_history"
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
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
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
    text = render_mod.audit_check_prompt(
        plan, intent, audit_detail, diff, plan_mod.plan_dir(root, slug)
    )
    sys.stdout.write(text)
    return 0


def cmd_ingest_audit_verdict(args: argparse.Namespace) -> int:
    root = _project_root()
    slug = _slug_from_args(args)
    text = sys.stdin.read() if args.stdin else (args.text or "")
    if not text:
        print("error: pass --stdin or --text", file=sys.stderr)
        return 1
    try:
        verdict = channels_mod.parse("audit_verdict", text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if verdict["verdict"] == "fail":
        with file_lock(plan_mod.lock_path(root, slug)):
            plan = plan_mod.load(root, slug)
            intent = plan_mod.find_intent(plan, args.intent)
            if intent and intent["status"] == "done" and verdict["recommend"] == "revert_to_open":
                plan_mod.revert_to_open(
                    plan,
                    args.intent,
                    {"reason": "layer2_audit_failed", "verdict": verdict},
                )
            plan_mod.save(root, plan, slug)

    events_mod.emit(
        root,
        "layer2_audit",
        {"intent": args.intent, "verdict": verdict},
        slug=slug,
    )
    if args.json:
        _print_json(verdict)
    return 0 if verdict["verdict"] == "pass" else 1


def cmd_render_reverse_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod

    root = _project_root()
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
    diff = _git_diff(root, args.diff_base)
    text = render_mod.reverse_audit_prompt(plan, diff, plan_mod.plan_dir(root, slug))
    sys.stdout.write(text)
    return 0


def cmd_ingest_reverse_verdict(args: argparse.Namespace) -> int:
    root = _project_root()
    slug = _slug_from_args(args)
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        verdict = channels_mod.parse("reverse_audit", text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rec = verdict["recommendation"]
    pdir = plan_mod.plan_dir(root, slug)
    if rec == "reopen_intents":
        with file_lock(plan_mod.lock_path(root, slug)):
            plan = plan_mod.load(root, slug)
            for r in verdict["regressions"]:
                intent_id = r.get("intent")
                if intent_id and plan_mod.find_intent(plan, intent_id):
                    plan_mod.revert_to_open(
                        plan,
                        intent_id,
                        {"reason": "reverse_audit_regression", "detail": r},
                    )
            plan_mod.save(root, plan, slug)
    elif rec == "rescope":
        steer = pdir / "Steer.md"
        existing = steer.read_text() if steer.exists() else ""
        steer.write_text(
            "# Reverse-audit recommends rescope\n\n"
            f"Goal gaps:\n- " + "\n- ".join(verdict["goal_gaps"])
            + f"\n\n---\n{existing}"
        )
    elif rec == "add_intents":
        steer = pdir / "Steer.md"
        existing = steer.read_text() if steer.exists() else ""
        steer.write_text(
            "# Reverse-audit recommends adding intents\n\n"
            f"Goal gaps that need new intents:\n- " + "\n- ".join(verdict["goal_gaps"])
            + f"\n\n---\n{existing}"
        )

    events_mod.emit(root, "reverse_audit", verdict, slug=slug)
    if args.json:
        _print_json(verdict)
    return 0 if verdict["clean"] else 2


def cmd_render_confidence_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod
    root = _project_root()
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
    sys.stdout.write(
        render_mod.confidence_audit_prompt(plan, plan_mod.plan_dir(root, slug))
    )
    return 0


def cmd_ingest_confidence(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        verdict = channels_mod.parse("confidence_audit", text)
    except signal_mod.SignalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    root = _project_root()
    slug = _slug_from_args(args)
    events_mod.emit(root, "confidence_audit", verdict, slug=slug)

    if verdict["recommendation"] == "rewrite_plan":
        steer = plan_mod.plan_dir(root, slug) / "Steer.md"
        existing = steer.read_text() if steer.exists() else ""
        loops_lines = "\n".join(
            f"- [{l.get('category')}] {l.get('problem')} → fix: {l.get('fix')}"
            for l in verdict["loopholes"]
        )
        steer.write_text(
            "# Confidence audit recommends rewriting the Plan\n\n"
            f"Loopholes ({len(verdict['loopholes'])}):\n{loops_lines}\n\n"
            "Run /gpr-grill again to redo the decomposition.\n\n"
            f"---\n{existing}"
        )

    if args.json:
        _print_json(verdict)
    else:
        print(f"confident: {verdict['confident']}")
        print(f"recommendation: {verdict['recommendation']}")
        if verdict["loopholes"]:
            print(f"loopholes: {len(verdict['loopholes'])}")
            for l in verdict["loopholes"]:
                print(f"  [{l.get('category', '?')}] {l.get('problem', '')}")
                print(f"    fix: {l.get('fix', '')}")
    return 0 if verdict["confident"] else 2


def cmd_render_commit_prompt(args: argparse.Namespace) -> int:
    from . import render as render_mod
    root = _project_root()
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
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
        msg = channels_mod.parse("commit", text)
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
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
    diff = _git_diff(root, args.diff_base)
    events = events_mod.tail(root, n=50, slug=slug)
    sys.stdout.write(render_mod.pr_description_prompt(plan, diff, events))
    return 0


def cmd_ingest_pr(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.stdin else (args.text or "")
    try:
        pr = channels_mod.parse("pr", text)
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


def _do_render(root: Path, args: argparse.Namespace) -> Path:
    from . import html_view
    from .state import config as config_mod
    slug = _slug_from_args(args)
    pdir = plan_mod.plan_dir(root, slug)
    plan = plan_mod.load(root, slug)
    state = budget_mod.load(root, slug)
    cfg = config_mod.load_effective(root)
    if args.style:
        cfg["viewer.style"] = args.style
    if args.theme:
        cfg["viewer.theme"] = args.theme
    if args.no_spotlight:
        cfg["viewer.spotlight"] = False
    if getattr(args, "auto_refresh", 0):
        cfg["viewer.auto_refresh"] = int(args.auto_refresh)
    out_path = Path(args.output) if args.output else (pdir / "Plan.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_view.render(plan, state, pdir, root, cfg))
    return out_path


def _resolve_jsonpath(obj: Any, path: str) -> Any:
    """Walk a dotted path with optional [N] array indexing.

    Examples:
      goal                         → obj["goal"]
      intents[0].id                → obj["intents"][0]["id"]
      globalState.iteration        → obj["globalState"]["iteration"]
      audit.details[0].result      → obj["audit"]["details"][0]["result"]
    """
    cursor = obj
    if not path:
        return cursor
    import re
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for raw in parts:
        if raw.startswith("[") and raw.endswith("]"):
            try:
                idx = int(raw[1:-1])
            except ValueError as exc:
                raise KeyError(f"bad array index {raw!r} in {path!r}") from exc
            if not isinstance(cursor, list):
                raise KeyError(f"{raw} on non-list at {path!r}")
            cursor = cursor[idx]
        else:
            if isinstance(cursor, dict):
                if raw not in cursor:
                    raise KeyError(f"missing key {raw!r} in {path!r}")
                cursor = cursor[raw]
            elif isinstance(cursor, list):
                try:
                    cursor = cursor[int(raw)]
                except (ValueError, IndexError) as exc:
                    raise KeyError(f"bad path segment {raw!r} in {path!r}") from exc
            else:
                raise KeyError(f"cannot index {raw!r} into {type(cursor).__name__}")
    return cursor


def cmd_get(args: argparse.Namespace) -> int:
    """Print a JSON field looked up by dotted path.

    Reads JSON from --stdin or a file path, walks the path, prints the bare
    value (newline-terminated for scalars; pretty-printed for containers
    when --json is given, else single-line).
    """
    if args.stdin:
        text = sys.stdin.read()
    elif args.file:
        text = Path(args.file).read_text()
    else:
        # Default: load Plan.json for the active plan.
        text = plan_mod.plan_path(
            _project_root(), _slug_from_args(args)
        ).read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    try:
        value = _resolve_jsonpath(data, args.path or "")
    except KeyError as exc:
        if args.default is not None:
            print(args.default)
            return 0
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json or isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2 if args.json else None))
    elif value is None:
        print("")
    else:
        print(value)
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    root = _project_root()
    out_path = _do_render(root, args)
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
    if args.watch:
        return _watch_render(root, args, out_path)
    return 0


def _watch_render(root: Path, args: argparse.Namespace, out_path: Path) -> int:
    """Re-render whenever a state file's mtime changes."""
    import time
    slug = _slug_from_args(args)
    pdir = plan_mod.plan_dir(root, slug)
    targets = [
        plan_mod.plan_path(root, slug),
        pdir / "Pinned.md",
        pdir / "Spine.md",
        pdir / "Steer.md",
        pdir / "errors.log",
        pdir / "events.jsonl",
        pdir / "budget.json",
    ]
    print(f"watching {len(targets)} files; re-rendering on change. ctrl-c to stop.")
    last: dict[str, float] = {}
    for p in targets:
        last[str(p)] = p.stat().st_mtime if p.exists() else 0.0
    try:
        while True:
            time.sleep(1.0)
            changed: list[str] = []
            for p in targets:
                m = p.stat().st_mtime if p.exists() else 0.0
                if m != last.get(str(p)):
                    changed.append(p.name)
                    last[str(p)] = m
            if changed:
                _do_render(root, args)
                print(f"[{plan_mod.utc_now()}] re-rendered ({', '.join(changed)})")
    except KeyboardInterrupt:
        print("\nwatch stopped.")
        return 0


def cmd_config(args: argparse.Namespace) -> int:
    from .state import config as config_mod
    root = _project_root()
    if args.action == "list":
        cfg = config_mod.load_effective(root)
        if args.json:
            _print_json(cfg)
            return 0
        for k in sorted(cfg.keys()):
            print(f"{k} = {cfg[k]!r}")
        return 0
    if args.action == "get":
        if not args.key:
            print("error: gpr config get <key>", file=sys.stderr)
            return 2
        v = config_mod.get(args.key, root)
        if args.json:
            _print_json({args.key: v})
        else:
            print(v)
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            print("error: gpr config set <key> <value>", file=sys.stderr)
            return 2
        v: Any = args.value
        default = config_mod.DEFAULTS.get(args.key)
        if isinstance(default, bool):
            v = args.value.lower() in {"1", "true", "yes", "on"}
        elif isinstance(default, int):
            try:
                v = int(args.value)
            except ValueError:
                print(f"error: {args.key} expects an integer", file=sys.stderr)
                return 2
        try:
            if args.scope == "project":
                config_mod.set_project(root, args.key, v)
            else:
                config_mod.set_user(args.key, v)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        scope_label = "project" if args.scope == "project" else "user"
        print(f"{scope_label}: {args.key} = {v!r}")
        return 0
    if args.action == "unset":
        if not args.key:
            print("error: gpr config unset <key>", file=sys.stderr)
            return 2
        if args.scope == "project":
            removed = config_mod.unset_project(root, args.key)
        else:
            removed = config_mod.unset_user(args.key)
        print(f"{'removed' if removed else 'not set'}: {args.key}")
        return 0
    if args.action == "reset":
        config_mod.reset_user()
        print("user config reset")
        return 0
    if args.action == "keys":
        for k in config_mod.list_keys():
            d = config_mod.DEFAULTS[k]
            print(f"{k}  (default: {d!r})")
        return 0
    print(f"error: unknown action {args.action!r}", file=sys.stderr)
    return 2


def cmd_revert_intent(args: argparse.Namespace) -> int:
    root = _project_root()
    slug = _slug_from_args(args)
    with file_lock(plan_mod.lock_path(root, slug)):
        plan = plan_mod.load(root, slug)
        plan_mod.revert_to_open(plan, args.intent, {"reason": args.reason or "manual_revert"})
        plan_mod.save(root, plan, slug)
    if args.json:
        _print_json({"ok": True, "intent": args.intent})
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    root = _project_root()
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
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
    slug = _slug_from_args(args)
    pdir = plan_mod.plan_dir(root, slug)
    pdir.mkdir(parents=True, exist_ok=True)
    steer = pdir / "Steer.md"
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
    slug = _slug_from_args(args)
    plan = plan_mod.load(root, slug)
    warnings = plan_mod.lint(plan)
    if args.json:
        _print_json({"warnings": warnings})
    else:
        for w in warnings:
            print(f"warning: {w}")
    return 0 if not warnings else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    import platform
    import shutil

    out: dict[str, Any] = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "checks": [],
    }
    rc = 0
    py_candidates = ("python3", "python") if platform.system() == "Windows" else ("python3",)
    py_path = next((shutil.which(c) for c in py_candidates if shutil.which(c)), None)
    out["checks"].append({"name": "python", "ok": bool(py_path), "path": py_path})
    if not py_path:
        rc = 1

    for name, cmd in [
        ("git", "git"),
        ("jq", "jq"),
        ("claude", "claude"),
        ("codex", "codex"),
        ("opencode", "opencode"),
        ("gemini", "gemini"),
    ]:
        path = shutil.which(cmd)
        out["checks"].append({"name": name, "ok": bool(path), "path": path})
        if name == "git" and not path:
            rc = 1

    timeout_path = shutil.which("timeout") or shutil.which("gtimeout")
    out["checks"].append({"name": "timeout", "ok": bool(timeout_path), "path": timeout_path})

    out["ok"] = rc == 0
    if args.json:
        _print_json(out)
    return rc


def cmd_record_budget(args: argparse.Namespace) -> int:
    """Record token+wall+cost from an iteration. Called by loop.sh."""
    root = _project_root()
    slug = _slug_from_args(args)
    state = budget_mod.load(root, slug)
    budget_mod.add_iteration(
        state,
        agent=args.agent,
        model=args.model,
        tokens_input=args.tokens_input,
        tokens_output=args.tokens_output,
        wall_seconds=args.wall_seconds,
    )
    plan = plan_mod.load(root, slug)
    bstatus = budget_mod.status(plan, state)
    if bstatus["wrap_up"] and not state.get("wrapUpEntered"):
        state["wrapUpEntered"] = True
        plan["globalState"]["wrapUpFlag"] = True
        plan_mod.save(root, plan, slug)
    budget_mod.save(root, state, slug)
    if args.json:
        _print_json(bstatus)
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Manage the named plans under .gpr/plans/."""
    root = _project_root()
    plan_mod.ensure_migration(root)
    action = args.action
    if action == "list":
        slugs = plan_mod.list_plans(root)
        active = plan_mod.read_active_slug(root) or plan_mod.DEFAULT_SLUG
        if args.json:
            entries = []
            for s in slugs:
                try:
                    p = plan_mod.load(root, s)
                except plan_mod.PlanError:
                    continue
                entries.append(
                    {
                        "slug": s,
                        "active": s == active,
                        "project": p["project"],
                        "goal": p["goal"],
                        "status": p.get("status", "pursuing"),
                        "intents_total": len(p["intents"]),
                        "intents_done": sum(
                            1 for it in p["intents"] if it["status"] == "done"
                        ),
                    }
                )
            _print_json({"active": active, "plans": entries})
        else:
            if not slugs:
                print("(no plans)")
                return 0
            for s in slugs:
                mark = "*" if s == active else " "
                try:
                    p = plan_mod.load(root, s)
                    label = f"{p['project']} :: {p['goal']}"
                except plan_mod.PlanError:
                    label = "(corrupt)"
                print(f"{mark} {s:<24} {label}")
        return 0
    if action == "use":
        if not args.slug:
            print("error: gpr plan use <slug>", file=sys.stderr)
            return 2
        slug = plan_mod.slugify(args.slug)
        if not plan_mod.plan_path(root, slug).exists():
            print(f"error: no plan {slug!r} (expected {plan_mod.plan_path(root, slug)})", file=sys.stderr)
            return 1
        plan_mod.write_active_slug(root, slug)
        print(f"active plan: {slug}")
        return 0
    if action == "current":
        active = plan_mod.read_active_slug(root) or plan_mod.DEFAULT_SLUG
        print(active)
        return 0
    if action == "rm":
        if not args.slug:
            print("error: gpr plan rm <slug>", file=sys.stderr)
            return 2
        slug = plan_mod.slugify(args.slug)
        target = plan_mod.plan_dir(root, slug)
        if not target.exists():
            print(f"error: no plan dir {target}", file=sys.stderr)
            return 1
        try:
            p = plan_mod.load(root, slug)
            if p.get("status", "pursuing") in {"pursuing", "rescope_pending"} and not args.force:
                print(
                    f"error: plan {slug!r} status={p['status']!r}; pass --force to delete",
                    file=sys.stderr,
                )
                return 1
        except plan_mod.PlanError:
            pass
        import shutil as _sh
        _sh.rmtree(target)
        active = plan_mod.read_active_slug(root)
        if active == slug:
            remaining = plan_mod.list_plans(root)
            if remaining:
                plan_mod.write_active_slug(root, remaining[0])
            else:
                plan_mod.active_plan_path(root).unlink(missing_ok=True)
        print(f"removed {target}")
        return 0
    if action == "rename":
        if not args.slug or not args.new:
            print("error: gpr plan rename <old> <new>", file=sys.stderr)
            return 2
        old = plan_mod.slugify(args.slug)
        new = plan_mod.slugify(args.new)
        src = plan_mod.plan_dir(root, old)
        dst = plan_mod.plan_dir(root, new)
        if not src.exists():
            print(f"error: no plan {old!r}", file=sys.stderr)
            return 1
        if dst.exists():
            print(f"error: plan {new!r} already exists", file=sys.stderr)
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        active = plan_mod.read_active_slug(root)
        if active == old:
            plan_mod.write_active_slug(root, new)
        print(f"renamed {old} -> {new}")
        return 0
    print(f"error: unknown action {action!r}", file=sys.stderr)
    return 2


def _extract_plan_from_markdown(text: str) -> dict[str, Any] | None:
    """Pull a JSON code block out of a markdown file. Returns dict or None."""
    import re as _re
    fences = _re.findall(
        r"```(?:json)?\s*\n(\{.*?\})\n```", text, _re.DOTALL | _re.IGNORECASE
    )
    for raw in fences:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "goal" in obj and "intents" in obj:
            return obj
    return None


def _load_external_plan(path: Path) -> dict[str, Any]:
    """Read a Plan from any of: Plan.json, plan.json, any *.json, Plan.md, *.md."""
    raw = path.read_text(errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".json" or raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"{path}: expected a JSON object at top level")
        return obj
    obj = _extract_plan_from_markdown(raw)
    if obj is None:
        raise ValueError(
            f"{path}: no Plan JSON found. Expected a JSON file or a markdown "
            "doc with a ```json fenced block containing a Plan."
        )
    return obj


def cmd_import(args: argparse.Namespace) -> int:
    """Fold an external Plan into .gpr/plans/<slug>/."""
    root = _project_root()
    plan_mod.ensure_migration(root)
    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        print(f"error: {src} does not exist", file=sys.stderr)
        return 1
    try:
        external = _load_external_plan(src)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    normalized = plan_mod.normalize_plan_dict(external, goal_fallback=src.stem)
    base_slug = args.name or normalized.get("project") or src.stem
    slug = plan_mod.slugify(base_slug)
    if plan_mod.plan_path(root, slug).exists() and not args.force:
        # Auto-suffix to avoid clobbering.
        n = 2
        while plan_mod.plan_path(root, f"{slug}-{n}").exists():
            n += 1
        slug = f"{slug}-{n}"
    pdir = plan_mod.plan_dir(root, slug)
    pdir.mkdir(parents=True, exist_ok=True)
    plan_mod.save(root, normalized, slug)
    # Seed plan-scoped support files.
    for fname, body in (
        ("Pinned.md", _pinned_template()),
        ("Spine.md", _spine_template(normalized.get("goal", ""))),
        ("Steer.md", ""),
    ):
        target = pdir / fname
        if not target.exists():
            target.write_text(body)
    (pdir / "errors.log").touch(exist_ok=True)
    if args.activate or plan_mod.read_active_slug(root) is None:
        plan_mod.write_active_slug(root, slug)
    if args.json:
        _print_json(
            {
                "ok": True,
                "slug": slug,
                "path": str(plan_mod.plan_path(root, slug)),
                "activated": args.activate
                or plan_mod.read_active_slug(root) == slug,
            }
        )
    else:
        print(f"imported {src.name} -> .gpr/plans/{slug}/Plan.json")
        if plan_mod.read_active_slug(root) == slug:
            print(f"active plan: {slug}")
        else:
            print(f"to activate: gpr plan use {slug}")
    return 0


# --- adapter registry (any CLI/TUI/model works) ------------------------------


def _agent_search_paths() -> list[Path]:
    """Resolution order for adapter JSON: project → user → built-in."""
    root = _project_root()
    user = Path(
        os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    ) / "gpr" / "agents"
    lib = Path(__file__).resolve().parent / "agents" / "builtin"
    return [root / ".gpr" / "agents", user, lib]


def _agent_load_json(name: str) -> dict[str, Any] | None:
    for d in _agent_search_paths():
        p = d / f"{name}.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
    return None


def _agent_list_all() -> dict[str, tuple[str, dict[str, Any]]]:
    """Return {name: (source, adapter_json)}. Project shadows user shadows built-in."""
    seen: dict[str, tuple[str, dict[str, Any]]] = {}
    for src_label, d in zip(
        ("builtin", "user", "project"), reversed(_agent_search_paths())
    ):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                obj = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            seen[f.stem] = (src_label, obj)
    return seen


def cmd_agent(args: argparse.Namespace) -> int:
    action = args.action
    if action == "list":
        all_ = _agent_list_all()
        if args.json:
            _print_json(
                {
                    name: {"source": src, "adapter": adapter}
                    for name, (src, adapter) in sorted(all_.items())
                }
            )
        else:
            if not all_:
                print("(no registered adapters; any CLI on PATH is auto-passthrough)")
            for name in sorted(all_.keys()):
                src, adapter = all_[name]
                cmd = adapter.get("cmd") or name
                print(f"  {name:<18} ({src})   cmd={cmd}")
        return 0
    if action == "show":
        if not args.name:
            print("error: gpr agent show <name>", file=sys.stderr)
            return 2
        adapter = _agent_load_json(args.name)
        if adapter is None:
            print(f"error: no adapter {args.name!r}", file=sys.stderr)
            return 1
        _print_json(adapter)
        return 0
    if action == "add":
        if not args.name:
            print("error: gpr agent add <name> --cmd <bin> [...]", file=sys.stderr)
            return 2
        target_root = (
            Path(_project_root()) / ".gpr" / "agents"
            if args.scope == "project"
            else Path(
                os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            ) / "gpr" / "agents"
        )
        target_root.mkdir(parents=True, exist_ok=True)
        adapter: dict[str, Any] = {
            "name": args.name,
            "cmd": args.cmd or args.name,
            "args": list(args.arg) if args.arg else [],
            "prompt": args.prompt_mode,
            "prompt_flag": args.prompt_flag,
            "model_flag": args.model_flag,
            "model_id_default": args.model_default,
            "stream_format": args.stream_format,
            "non_interactive_flags": list(args.flag) if args.flag else [],
            "timeout_seconds": args.timeout_seconds,
        }
        if args.cost_input is not None and args.cost_output is not None:
            adapter["cost_rates_per_mtok"] = {
                "input": float(args.cost_input),
                "output": float(args.cost_output),
            }
        (target_root / f"{args.name}.json").write_text(
            json.dumps(adapter, indent=2) + "\n"
        )
        print(f"wrote {target_root / (args.name + '.json')}")
        return 0
    if action == "rm":
        if not args.name:
            print("error: gpr agent rm <name>", file=sys.stderr)
            return 2
        for d in _agent_search_paths()[:-1]:  # never remove built-in
            p = d / f"{args.name}.json"
            if p.exists():
                p.unlink()
                print(f"removed {p}")
                return 0
        print(f"error: no user/project adapter {args.name!r} to remove", file=sys.stderr)
        return 1
    print(f"error: unknown action {action!r}", file=sys.stderr)
    return 2


def cmd_record_signature(args: argparse.Namespace) -> int:
    """Update payload-hash + checkbox count signature, return stalemate status."""
    root = _project_root()
    slug = _slug_from_args(args)
    pdir = plan_mod.plan_dir(root, slug)
    plan = plan_mod.load(root, slug)
    h = stalemate_mod.git_diff_hash(root)
    cb = stalemate_mod.checkbox_count(pdir / "Spine.md")
    stalled, deltas = stalemate_mod.update_signature(plan, h, cb)
    plan_mod.save(root, plan, slug)
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


def _add_plan_arg(parser: argparse.ArgumentParser) -> None:
    """Attach --plan <slug> to a subparser.

    Resolution if absent: $GPR_PLAN → .gpr/active → "default". Auto-migration
    of any legacy top-level .gpr/Plan.json into .gpr/plans/default/ runs on
    first invocation of any command in a project.
    """
    parser.add_argument(
        "--plan",
        default=None,
        metavar="SLUG",
        help="Operate on the named plan under .gpr/plans/<slug>/.",
    )


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
    _add_plan_arg(pi)
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("status")
    ps.add_argument("--json", action="store_true")
    _add_plan_arg(ps)
    ps.set_defaults(func=cmd_status)

    pn = sub.add_parser("next-intent")
    pn.add_argument("--json", action="store_true")
    pn.add_argument("--stale-seconds", type=int, default=plan_mod.STALE_SECONDS_DEFAULT)
    _add_plan_arg(pn)
    pn.set_defaults(func=cmd_next_intent)

    pr = sub.add_parser("render-prompt")
    pr.add_argument("--intent", default=None)
    _add_plan_arg(pr)
    pr.set_defaults(func=cmd_render_prompt)

    pis = sub.add_parser("ingest-signal")
    pis.add_argument("--stdin", action="store_true")
    pis.add_argument("--text", default=None)
    pis.add_argument("--intent", default=None)
    pis.add_argument("--json", action="store_true")
    _add_plan_arg(pis)
    pis.set_defaults(func=cmd_ingest_signal)

    prap = sub.add_parser("render-audit-prompt")
    prap.add_argument("--intent", required=True)
    prap.add_argument("--audit-json", default=None,
                      help="Path to a saved audit.json from the iter dir")
    prap.add_argument("--diff-base", default="HEAD")
    _add_plan_arg(prap)
    prap.set_defaults(func=cmd_render_audit_prompt)

    piav = sub.add_parser("ingest-audit-verdict")
    piav.add_argument("--intent", required=True)
    piav.add_argument("--stdin", action="store_true")
    piav.add_argument("--text", default=None)
    piav.add_argument("--json", action="store_true")
    _add_plan_arg(piav)
    piav.set_defaults(func=cmd_ingest_audit_verdict)

    prrp = sub.add_parser("render-reverse-prompt")
    prrp.add_argument("--diff-base", default="HEAD")
    _add_plan_arg(prrp)
    prrp.set_defaults(func=cmd_render_reverse_prompt)

    pirv = sub.add_parser("ingest-reverse-verdict")
    pirv.add_argument("--stdin", action="store_true")
    pirv.add_argument("--text", default=None)
    pirv.add_argument("--json", action="store_true")
    _add_plan_arg(pirv)
    pirv.set_defaults(func=cmd_ingest_reverse_verdict)

    pcap = sub.add_parser("render-confidence-prompt")
    _add_plan_arg(pcap)
    pcap.set_defaults(func=cmd_render_confidence_prompt)

    picon = sub.add_parser("ingest-confidence")
    picon.add_argument("--stdin", action="store_true")
    picon.add_argument("--text", default=None)
    picon.add_argument("--json", action="store_true")
    _add_plan_arg(picon)
    picon.set_defaults(func=cmd_ingest_confidence)

    pcp = sub.add_parser("render-commit-prompt")
    pcp.add_argument("--intent", required=True)
    pcp.add_argument("--audit-json", default=None)
    pcp.add_argument("--diff-base", default="HEAD")
    _add_plan_arg(pcp)
    pcp.set_defaults(func=cmd_render_commit_prompt)

    pic = sub.add_parser("ingest-commit")
    pic.add_argument("--stdin", action="store_true")
    pic.add_argument("--text", default=None)
    pic.add_argument("--apply", action="store_true",
                     help="Run git commit with the parsed message")
    pic.add_argument("--json", action="store_true")
    _add_plan_arg(pic)
    pic.set_defaults(func=cmd_ingest_commit)

    pprp = sub.add_parser("render-pr-prompt")
    pprp.add_argument("--diff-base", default="HEAD")
    _add_plan_arg(pprp)
    pprp.set_defaults(func=cmd_render_pr_prompt)

    pipr = sub.add_parser("ingest-pr")
    pipr.add_argument("--stdin", action="store_true")
    pipr.add_argument("--text", default=None)
    pipr.add_argument("--output", default=None,
                      help="Write the PR body to a file")
    pipr.add_argument("--json", action="store_true")
    _add_plan_arg(pipr)
    pipr.set_defaults(func=cmd_ingest_pr)

    pg = sub.add_parser("get",
                        help="Print a JSON field by dotted path. Reads the active Plan.json by default.")
    pg.add_argument("path", help="dotted path: goal | intents[0].id | globalState.iteration")
    pg.add_argument("--stdin", action="store_true",
                    help="Read JSON from stdin instead of Plan.json")
    pg.add_argument("--file", default=None,
                    help="Read JSON from this file instead of Plan.json")
    pg.add_argument("--default", default=None,
                    help="Print this if path is missing instead of erroring")
    pg.add_argument("--json", action="store_true",
                    help="Pretty-print containers and quote scalars as JSON")
    _add_plan_arg(pg)
    pg.set_defaults(func=cmd_get)

    prn = sub.add_parser("render")
    prn.add_argument("--output", default=None,
                     help="Output path (default: .gpr/Plan.html)")
    prn.add_argument("--open", action="store_true",
                     help="Open the rendered file in the default browser")
    prn.add_argument("--style", default=None,
                     choices=["editorial", "terminal", "notebook", "brutalist"],
                     help="Override the viewer style for this render")
    prn.add_argument("--theme", default=None,
                     choices=["paper", "sepia", "dark", "arctic"],
                     help="Override the theme for this render")
    prn.add_argument("--no-spotlight", action="store_true",
                     help="Disable the spotlight cursor for this render")
    prn.add_argument("--watch", action="store_true",
                     help="Re-render on every state-file change. Ctrl-C to stop.")
    prn.add_argument("--auto-refresh", type=int, default=0, metavar="SECONDS",
                     help="Embed an HTML meta-refresh tag with this interval. "
                          "Pairs with --watch for hands-off live updates.")
    prn.add_argument("--json", action="store_true")
    _add_plan_arg(prn)
    prn.set_defaults(func=cmd_render)

    pcg = sub.add_parser("config")
    pcg.add_argument("action", choices=["list", "get", "set", "unset", "reset", "keys"])
    pcg.add_argument("key", nargs="?", default=None)
    pcg.add_argument("value", nargs="?", default=None)
    pcg.add_argument("--scope", choices=["user", "project"], default="user")
    pcg.add_argument("--json", action="store_true")
    pcg.set_defaults(func=cmd_config)

    pri = sub.add_parser("revert-intent")
    pri.add_argument("--intent", required=True)
    pri.add_argument("--reason", default=None)
    pri.add_argument("--json", action="store_true")
    _add_plan_arg(pri)
    pri.set_defaults(func=cmd_revert_intent)

    pa = sub.add_parser("audit")
    pa.add_argument("--intent", default=None)
    pa.add_argument("--reverse", action="store_true")
    pa.add_argument("--json", action="store_true")
    _add_plan_arg(pa)
    pa.set_defaults(func=cmd_audit)

    pt = sub.add_parser("steer")
    pt.add_argument("--abort", action="store_true")
    pt.add_argument("message", nargs="?", default="")
    _add_plan_arg(pt)
    pt.set_defaults(func=cmd_steer)

    pl = sub.add_parser("lint")
    pl.add_argument("--json", action="store_true")
    _add_plan_arg(pl)
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
    _add_plan_arg(pb)
    pb.set_defaults(func=cmd_record_budget)

    psg = sub.add_parser("record-signature")
    psg.add_argument("--json", action="store_true")
    _add_plan_arg(psg)
    psg.set_defaults(func=cmd_record_signature)

    # --- multi-plan management ------------------------------------------------

    pplan = sub.add_parser("plan", help="List / switch / remove plans.")
    pplan.add_argument(
        "action", choices=["list", "use", "current", "rm", "rename"]
    )
    pplan.add_argument("slug", nargs="?", default=None)
    pplan.add_argument("new", nargs="?", default=None,
                       help="for `plan rename <old> <new>`")
    pplan.add_argument("--force", action="store_true",
                       help="`plan rm` against a non-paused plan")
    pplan.add_argument("--json", action="store_true")
    pplan.set_defaults(func=cmd_plan)

    pimport = sub.add_parser(
        "import",
        help="Fold an external Plan.json / plan.md into .gpr/plans/<slug>/.",
    )
    pimport.add_argument("source", help="path to Plan JSON or markdown file")
    pimport.add_argument("--name", default=None,
                         help="slug to import as (default: from project/filename)")
    pimport.add_argument("--activate", action="store_true",
                         help="also write .gpr/active so /gpr targets this plan")
    pimport.add_argument("--force", action="store_true",
                         help="overwrite an existing plan with the same slug")
    pimport.add_argument("--json", action="store_true")
    pimport.set_defaults(func=cmd_import)

    pagent = sub.add_parser(
        "agent", help="Register / list / show / remove agent adapters."
    )
    pagent.add_argument("action", choices=["list", "show", "add", "rm"])
    pagent.add_argument("name", nargs="?", default=None)
    pagent.add_argument("--cmd", default=None, help="binary to invoke")
    pagent.add_argument("--arg", action="append", default=[],
                        help="flag to pass before the prompt (repeatable)")
    pagent.add_argument(
        "--prompt-mode",
        choices=["stdin", "argv_last", "argv_named"],
        default="stdin",
        help="how the binary expects the prompt (default: stdin)",
    )
    pagent.add_argument("--prompt-flag", default=None,
                        help="flag for --prompt-mode argv_named (e.g. --prompt)")
    pagent.add_argument("--model-flag", default=None,
                        help="flag this CLI uses for model selection (e.g. --model)")
    pagent.add_argument("--model-default", default=None,
                        help="model id to record for cost accounting when GPR_MODEL is unset")
    pagent.add_argument(
        "--stream-format",
        choices=["passthrough", "claude_stream_json", "codex_json"],
        default="passthrough",
        help="token-usage parser for this CLI's stdout (default: passthrough)",
    )
    pagent.add_argument("--flag", action="append", default=[],
                        help="non-interactive flag (e.g. --yolo); repeatable")
    pagent.add_argument("--timeout-seconds", type=int, default=1800)
    pagent.add_argument("--cost-input", type=float, default=None,
                        help="USD per million input tokens (cost accounting)")
    pagent.add_argument("--cost-output", type=float, default=None,
                        help="USD per million output tokens (cost accounting)")
    pagent.add_argument("--scope", choices=["user", "project"], default="user")
    pagent.add_argument("--json", action="store_true")
    pagent.set_defaults(func=cmd_agent)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
