"""Render the Plan as a single-file interactive HTML PRD viewer.

Architecture (from cleanroom deep research):
- Vanilla HTML + Alpine.js for declarative interactivity, no build.
- Three-column layout: sticky TOC rail (with scroll-progress fill),
  the paper card (editorial body), and a marginalia rail for
  decisions, drift, and open questions.
- Phase Gateway (Specify → Plan → Tasks → Implement → Done) maps
  each intent into a phase derived from its status + dependency
  satisfaction. Reader gets a one-glance picture of the run state.
- Intents are hover/focus-expanding cards (CSS-only via
  grid-template-rows transition); click toggles a sticky open state.
- Acceptance Criteria rendered in Given/When/Then per Check.
- Mermaid DAG is click-to-zoom into a fullscreen <dialog> with
  svg-pan-zoom controls.
- Cmd-K palette indexes every section heading, intent, check, and
  event; arrow keys + Enter to jump.
- Spotlight cursor: a subtle radial-gradient blob follows the
  pointer with rAF lerp.
- Theme toggle: paper / sepia / dark / arctic.
- Print stylesheet expands every <details> and breaks intents on
  page boundaries.

Cleanroom — no proprietary class names, no copied prompts,
no replicated layouts from commercial PRD products.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import budget as budget_mod
from .state import events as events_mod


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def _completion_glyph(intent: dict[str, Any]) -> str:
    if intent["status"] == "done":
        return "●"
    if intent["status"] == "paused":
        return "◐"
    proofs = {p.get("checkId") for p in intent.get("proofs", [])}
    if not intent.get("checks"):
        return "○"
    proven = sum(1 for c in intent["checks"] if c["id"] in proofs)
    if proven == 0:
        return "○"
    if proven == len(intent["checks"]):
        return "●"
    return "◐"


def _check_glyph_class(intent: dict[str, Any], check_id: str) -> str:
    proofs = {p.get("checkId"): p for p in intent.get("proofs", [])}
    if check_id in proofs:
        return "glyph-pass"
    failures = [
        f for f in intent.get("auditFailures", [])
        for d in f.get("audit", {}).get("details", [])
        if d.get("checkId") == check_id and d.get("result") == "fail"
    ]
    if failures:
        return "glyph-fail"
    return "glyph-pending"


def _phase_for(intent: dict[str, Any], all_done_ids: set[str]) -> str:
    """Derive a Phase Gateway phase from intent status + dependency state."""
    s = intent["status"]
    if s == "done":
        return "implement"
    if s == "in_progress":
        return "tasks"
    if s == "paused":
        return "paused"
    deps_satisfied = all(d in all_done_ids for d in intent.get("dependsOn", []))
    if deps_satisfied:
        return "plan"
    return "specify"


PHASE_LABELS = {
    "specify": ("Specify", "Goal sketched. Dependencies still need to land."),
    "plan": ("Plan", "Ready to grab. Dependencies satisfied."),
    "tasks": ("Tasks", "In flight this round."),
    "implement": ("Implement", "Audit passed. Code shipped."),
    "paused": ("Paused", "Held for human."),
}


def _intent_dag_mermaid(plan: dict[str, Any]) -> str:
    lines = ["graph LR"]
    for it in plan["intents"]:
        node_id = _esc(it["id"])
        title = _esc(it["title"])[:32]
        cls = {
            "open": "open",
            "in_progress": "wip",
            "done": "done",
            "paused": "paused",
        }.get(it["status"], "open")
        lines.append(f'    {node_id}["{node_id}<br/>{title}"]:::{cls}')
        for dep in it["dependsOn"]:
            lines.append(f"    {_esc(dep)} --> {node_id}")
    lines.append("    classDef open fill:transparent,stroke:#bcb6a8,color:#44403c")
    lines.append("    classDef wip fill:transparent,stroke:#1f3873,color:#1f3873,stroke-width:2px")
    lines.append("    classDef done fill:transparent,stroke:#16614b,color:#16614b")
    lines.append("    classDef paused fill:transparent,stroke:#92400e,color:#92400e")
    return "\n".join(lines)


def _intent_card_html(idx: int, intent: dict[str, Any], all_done_ids: set[str]) -> str:
    num = f"{idx:02d}"
    deps = ", ".join(_esc(d) for d in intent["dependsOn"]) or "—"
    phase = _phase_for(intent, all_done_ids)
    phase_label, _ = PHASE_LABELS[phase]

    checks_html_lines = []
    for ch in intent.get("checks", []):
        gcls = _check_glyph_class(intent, ch["id"])
        cmd = ch.get("verifyCmd")
        cmd_html = (
            f'<div class="cmd-row"><code class="cmd">{_esc(cmd)}</code>'
            f'<button class="copy-btn" data-copy="{_esc(cmd)}" title="copy">copy</button></div>'
            if cmd else
            '<div class="cmd cmd-manual">manual gate</div>'
        )
        checks_html_lines.append(
            f'<li class="check-item">'
            f'<span class="check-glyph {gcls}">●</span>'
            f'<div class="check-body">'
            f'<div class="check-head"><span class="check-id">{_esc(ch["id"])}</span> '
            f'<span class="check-desc">{_esc(ch["description"])}</span></div>'
            f'{cmd_html}'
            '</div></li>'
        )
    checks_html = "".join(checks_html_lines)

    fails_html = ""
    fails = intent.get("auditFailures", [])
    if fails:
        latest = fails[-1]
        fails_html = (
            '<details class="audit-failure">'
            '<summary>last audit failure</summary>'
            f'<pre>{_esc(json.dumps(latest, indent=2)[:600])}</pre>'
            '</details>'
        )

    proofs_count = len(intent.get("proofs", []))
    checks_count = len(intent.get("checks", []))

    return (
        f'<article id="intent-{_esc(intent["id"])}" '
        f'class="intent-card" '
        f'data-status="{_esc(intent["status"])}" '
        f'data-phase="{phase}" '
        f'data-id="{_esc(intent["id"])}" '
        f'data-title="{_esc(intent["title"]).lower()}" '
        f'x-data="{{ open: false }}">'

        f'<header class="intent-summary" tabindex="0" @click="open = !open" '
        f'@keydown.enter.prevent="open = !open" @keydown.space.prevent="open = !open" '
        f':aria-expanded="open">'
        f'<div class="intent-num">{num}</div>'
        f'<div class="intent-headline">'
        f'<h3 class="intent-title">{_esc(intent["title"])}</h3>'
        f'<div class="intent-meta">'
        f'<span class="phase-pill phase-{phase}" title="phase: {phase_label}">{phase_label}</span>'
        f'<span class="status status-{_esc(intent["status"])}">{_esc(intent["status"].replace("_", " "))}</span>'
        f'<span class="meta">priority {_esc(intent["priority"])}</span>'
        f'<span class="meta">depends · {_esc(deps)}</span>'
        f'</div>'
        f'</div>'
        f'<div class="intent-counters">'
        f'<span class="counter-num">{proofs_count}<span class="counter-frac">/{checks_count}</span></span>'
        f'<span class="counter-label">proofs</span>'
        f'</div>'
        f'<button class="copy-btn copy-id" data-copy="{_esc(intent["id"])}" '
        f'@click.stop>{_esc(intent["id"])}</button>'
        f'<span class="chevron" :class="{{ \'open\': open }}">›</span>'
        f'</header>'

        f'<div class="intent-detail" x-show="open" x-collapse>'
        f'<div class="intent-detail-inner">'
        f'<ul class="checks">{checks_html}</ul>'
        f'{fails_html}'
        f'</div>'
        f'</div>'
        '</article>'
    )


def _toc_html(plan: dict[str, Any]) -> str:
    rows = []
    for it in plan["intents"]:
        rows.append(
            f'<li data-toc-id="{_esc(it["id"])}" data-status="{_esc(it["status"])}">'
            f'<a href="#intent-{_esc(it["id"])}">'
            f'<span class="toc-glyph">{_completion_glyph(it)}</span>'
            f'<span class="toc-id">{_esc(it["id"])}</span>'
            f'<span class="toc-title">{_esc(it["title"])}</span>'
            f'</a></li>'
        )
    return f'<ol class="toc-list">{"".join(rows)}</ol>'


def _phase_gateway_html(plan: dict[str, Any]) -> str:
    all_done_ids = {it["id"] for it in plan["intents"] if it["status"] == "done"}
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in PHASE_LABELS}
    for it in plan["intents"]:
        buckets[_phase_for(it, all_done_ids)].append(it)
    columns = []
    order = ["specify", "plan", "tasks", "implement"]
    for phase in order:
        items = buckets[phase]
        label, hint = PHASE_LABELS[phase]
        cards = "".join(
            f'<a class="gw-item" href="#intent-{_esc(it["id"])}">'
            f'<span class="gw-id">{_esc(it["id"])}</span>'
            f'<span class="gw-title">{_esc(it["title"])[:34]}</span>'
            f'</a>'
            for it in items
        ) or '<span class="gw-empty">—</span>'
        columns.append(
            f'<div class="gw-col" data-phase="{phase}">'
            f'<div class="gw-head">'
            f'<span class="gw-label">{label}</span>'
            f'<span class="gw-count">{len(items)}</span>'
            f'</div>'
            f'<div class="gw-hint">{hint}</div>'
            f'<div class="gw-items">{cards}</div>'
            f'</div>'
        )
    paused = buckets["paused"]
    paused_html = ""
    if paused:
        paused_html = (
            '<div class="gw-paused">'
            '<span class="gw-label">Paused</span>'
            + "".join(
                f'<a class="gw-item" href="#intent-{_esc(it["id"])}">{_esc(it["id"])} · {_esc(it["title"])[:32]}</a>'
                for it in paused
            )
            + '</div>'
        )
    return f'<div class="gateway">{"".join(columns)}</div>{paused_html}'


def _acceptance_html(plan: dict[str, Any]) -> str:
    rows = []
    for it in plan["intents"]:
        for ch in it.get("checks", []):
            cmd = ch.get("verifyCmd")
            given = f"intent {_esc(it['id'])} ({_esc(it['title'])}) is in scope"
            when = (
                f"running <code class=\"inline-cmd\">{_esc(cmd)}</code>"
                if cmd else "the manual gate is reviewed"
            )
            then = _esc(ch["description"])
            gcls = _check_glyph_class(it, ch["id"])
            rows.append(
                '<li class="ac-item">'
                f'<span class="check-glyph {gcls}">●</span>'
                f'<div class="ac-body">'
                f'<div class="ac-id">{_esc(it["id"])} · {_esc(ch["id"])}</div>'
                f'<div><span class="ac-kw">Given</span> {given}</div>'
                f'<div><span class="ac-kw">When</span> {when}</div>'
                f'<div><span class="ac-kw">Then</span> {then}</div>'
                '</div></li>'
            )
    if not rows:
        return '<p class="empty">no acceptance criteria yet</p>'
    return f'<ul class="ac-list">{"".join(rows)}</ul>'


def _decision_log_html(plan: dict[str, Any], project_root: Path) -> str:
    decisions: list[dict[str, Any]] = []
    for it in plan["intents"]:
        for f in it.get("auditFailures", []):
            decisions.append({
                "kind": "audit-fail",
                "intent": it["id"],
                "title": it["title"],
                "ts": f.get("at", ""),
                "detail": f.get("reason", "audit failure"),
            })
    events = events_mod.tail(project_root, n=80)
    for e in events:
        ts = e.get("t", 0)
        ts_iso = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if ts else ""
        )
        if e.get("kind") == "reverse_audit":
            decisions.append({
                "kind": "reverse-audit",
                "ts": ts_iso,
                "detail": f"recommendation: {e.get('recommendation')} — clean: {e.get('clean')}",
            })
        elif e.get("kind") == "layer2_audit":
            v = e.get("verdict", {})
            decisions.append({
                "kind": "layer-2",
                "intent": e.get("intent", ""),
                "ts": ts_iso,
                "detail": f"verdict: {v.get('verdict')} · " + ", ".join(v.get("reasons", [])),
            })
        elif e.get("kind") == "confidence_audit":
            decisions.append({
                "kind": "confidence",
                "ts": ts_iso,
                "detail": f"confident: {e.get('confident')} · loopholes: {len(e.get('loopholes') or [])}",
            })
    decisions.sort(key=lambda d: d.get("ts", ""), reverse=True)
    if not decisions:
        return '<p class="empty">no decisions logged yet — audits will appear here</p>'
    rows = []
    for d in decisions[:30]:
        rows.append(
            '<li class="decision-item">'
            f'<span class="decision-kind">{_esc(d["kind"])}</span>'
            + (f'<span class="decision-intent">{_esc(d.get("intent", ""))}</span>' if d.get("intent") else "")
            + f'<span class="decision-ts">{_esc(d.get("ts", ""))}</span>'
            f'<span class="decision-detail">{_esc(d.get("detail", ""))}</span>'
            '</li>'
        )
    return f'<ul class="decision-list">{"".join(rows)}</ul>'


def _events_html(project_root: Path, n: int = 30) -> str:
    events = events_mod.tail(project_root, n=n)
    if not events:
        return '<p class="empty">no events yet</p>'
    rows = []
    for e in reversed(events):
        kind = _esc(e.get("kind", "?"))
        ts = e.get("t", 0)
        time_str = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
            if ts else "?"
        )
        if kind == "iteration":
            sig = e.get("signal", {})
            detail = f"intent={_esc(sig.get('intent'))} status={_esc(sig.get('status'))}"
            audit = e.get("audit") or {}
            if audit:
                detail += f"  audit={audit.get('pass', 0)}/{audit.get('pass', 0)+audit.get('fail', 0)+audit.get('manual', 0)}"
        elif kind == "layer2_audit":
            v = e.get("verdict", {})
            detail = f"intent={_esc(e.get('intent'))} verdict={_esc(v.get('verdict'))}"
        elif kind == "reverse_audit":
            detail = f"clean={_esc(e.get('clean'))} rec={_esc(e.get('recommendation'))}"
        elif kind == "confidence_audit":
            detail = f"confident={_esc(e.get('confident'))} loopholes={len(e.get('loopholes') or [])}"
        else:
            detail = ""
        rows.append(
            '<tr>'
            f'<td class="ev-time">{time_str}</td>'
            f'<td class="ev-kind">{kind}</td>'
            f'<td class="ev-detail">{detail}</td>'
            '</tr>'
        )
    return f'<table class="events">{"".join(rows)}</table>'


def _command_palette_data(plan: dict[str, Any]) -> str:
    """Build the searchable command list as a JSON literal Alpine reads."""
    items: list[dict[str, str]] = []
    items.extend([
        {"kind": "section", "label": "Goal", "target": "#section-goal"},
        {"kind": "section", "label": "Phase Gateway", "target": "#section-phases"},
        {"kind": "section", "label": "Intent Graph", "target": "#section-graph"},
        {"kind": "section", "label": "Intents", "target": "#section-intents"},
        {"kind": "section", "label": "Acceptance Criteria", "target": "#section-ac"},
        {"kind": "section", "label": "Decision Log", "target": "#section-decisions"},
        {"kind": "section", "label": "Events", "target": "#section-events"},
        {"kind": "action", "label": "Theme: paper", "action": "theme:paper"},
        {"kind": "action", "label": "Theme: sepia", "action": "theme:sepia"},
        {"kind": "action", "label": "Theme: dark", "action": "theme:dark"},
        {"kind": "action", "label": "Theme: arctic", "action": "theme:arctic"},
        {"kind": "action", "label": "Filter: all", "action": "filter:all"},
        {"kind": "action", "label": "Filter: open", "action": "filter:open"},
        {"kind": "action", "label": "Filter: in_progress", "action": "filter:in_progress"},
        {"kind": "action", "label": "Filter: done", "action": "filter:done"},
        {"kind": "action", "label": "Filter: paused", "action": "filter:paused"},
        {"kind": "action", "label": "Open intent graph fullscreen", "action": "graph:fullscreen"},
        {"kind": "action", "label": "Toggle spotlight cursor", "action": "spotlight:toggle"},
        {"kind": "action", "label": "Story mode (toggle)", "action": "mode:story"},
        {"kind": "action", "label": "Normal mode", "action": "mode:normal"},
        {"kind": "action", "label": "Style: editorial", "action": "style:editorial"},
        {"kind": "action", "label": "Style: terminal", "action": "style:terminal"},
        {"kind": "action", "label": "Style: notebook", "action": "style:notebook"},
        {"kind": "action", "label": "Style: brutalist", "action": "style:brutalist"},
        {"kind": "action", "label": "Font size: compact", "action": "fontsize:compact"},
        {"kind": "action", "label": "Font size: default", "action": "fontsize:default"},
        {"kind": "action", "label": "Font size: large", "action": "fontsize:large"},
        {"kind": "action", "label": "Print PRD", "action": "print"},
    ])
    for it in plan["intents"]:
        items.append({
            "kind": "intent",
            "label": f"{it['id']} · {it['title']}",
            "target": f"#intent-{it['id']}",
        })
        for ch in it.get("checks", []):
            items.append({
                "kind": "check",
                "label": f"{it['id']} · {ch['id']} — {ch['description'][:80]}",
                "target": f"#intent-{it['id']}",
            })
    return json.dumps(items)


CSS = r"""
:root[data-theme="paper"] {
  --bg: #fbfaf6;
  --paper: #ffffff;
  --ink: #1c1917;
  --ink-muted: #57534e;
  --ink-faint: #a8a29e;
  --hairline: #eae7e1;
  --hairline-strong: #d6d3d1;
  --accent: #1f3873;
  --accent-soft: #6582bd;
  --accent-faint: #f5f7fb;
  --pass: #16614b;
  --fail: #b91c1c;
  --warn: #92400e;
  --paper-shadow: 0 1px 4px 1px rgba(0,0,0,0.05),
                  0 1px 1px 0 rgba(0,0,0,0.05),
                  0 -1px 1px 1px #ffffff inset;
  --spotlight: rgba(31,56,115,0.06);
}
:root[data-theme="sepia"] {
  --bg: #f4ecd8;
  --paper: #fbf6e8;
  --ink: #2b2412;
  --ink-muted: #6b5d3f;
  --ink-faint: #b8a986;
  --hairline: #e2d4a8;
  --hairline-strong: #c8b785;
  --accent: #6b3a1d;
  --accent-soft: #9a6238;
  --accent-faint: #f5ecd0;
  --pass: #426d3c;
  --fail: #8a3215;
  --warn: #7a4f17;
  --paper-shadow: 0 1px 4px 1px rgba(74,57,28,0.10),
                  0 1px 1px 0 rgba(74,57,28,0.06),
                  0 -1px 1px 1px #fdf8e8 inset;
  --spotlight: rgba(107,58,29,0.08);
}
:root[data-theme="dark"] {
  --bg: #0f0e0c;
  --paper: #181613;
  --ink: #f5f3ee;
  --ink-muted: #a8a29e;
  --ink-faint: #57534e;
  --hairline: #2a2724;
  --hairline-strong: #3f3a35;
  --accent: #8fa4d2;
  --accent-soft: #6582bd;
  --accent-faint: #1c2238;
  --pass: #4ade80;
  --fail: #f87171;
  --warn: #fbbf24;
  --paper-shadow: 0 1px 0 0 rgba(255,255,255,0.04) inset,
                  0 1px 8px 1px rgba(0,0,0,0.5);
  --spotlight: rgba(143,164,210,0.10);
}
:root[data-theme="arctic"] {
  --bg: #eef3f6;
  --paper: #fbfdfe;
  --ink: #0f172a;
  --ink-muted: #475569;
  --ink-faint: #94a3b8;
  --hairline: #d8e1ea;
  --hairline-strong: #b6c4d2;
  --accent: #0f4c75;
  --accent-soft: #4a7ba6;
  --accent-faint: #e6eef5;
  --pass: #0e7c6a;
  --fail: #b91c1c;
  --warn: #92400e;
  --paper-shadow: 0 1px 4px 1px rgba(15,76,117,0.06),
                  0 1px 1px 0 rgba(15,76,117,0.04),
                  0 -1px 1px 1px #ffffff inset;
  --spotlight: rgba(15,76,117,0.08);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: 'EB Garamond', Georgia, 'Times New Roman', serif;
  font-feature-settings: 'liga', 'calt';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  transition: background 200ms ease, color 200ms ease;
}

/* === STORY MODE === */
:root[data-mode="story"] .toolbar,
:root[data-mode="story"] .toc-rail,
:root[data-mode="story"] .marginalia,
:root[data-mode="story"] .spotlight,
:root[data-mode="story"] .scroll-rail-top,
:root[data-mode="story"] .gateway,
:root[data-mode="story"] .mermaid-frame::after,
:root[data-mode="story"] #section-events,
:root[data-mode="story"] .intent-counters,
:root[data-mode="story"] .copy-btn,
:root[data-mode="story"] .copy-id,
:root[data-mode="story"] .chevron,
:root[data-mode="story"] .phase-pill { display: none !important; }
:root[data-mode="story"] .layout {
  display: block; max-width: 720px; padding: 64px 24px 120px;
}
:root[data-mode="story"] .paper {
  box-shadow: none; padding: 0; background: transparent;
}
:root[data-mode="story"] .intent-card { border: none; background: transparent; margin-bottom: 32px; }
:root[data-mode="story"] .intent-summary { padding: 0; cursor: default; }
:root[data-mode="story"] .intent-detail { display: block !important; height: auto !important; overflow: visible !important; border-top: none; }
:root[data-mode="story"] .intent-detail-inner { padding: 12px 0 0 0; }
:root[data-mode="story"] .intent-title { font-size: 24px; }
:root[data-mode="story"] body { font-size: 18px; }
:root[data-mode="story"] .section-h::after { display: none; }
:root[data-mode="story"] .section-h::before {
  content: ""; display: block; width: 24px; height: 1px;
  background: var(--ink-faint); margin-bottom: 12px;
}
.story-exit {
  position: fixed; top: 24px; right: 24px; z-index: 50;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  padding: 6px 12px; border: 1px solid var(--hairline-strong);
  background: var(--paper); color: var(--ink-muted); border-radius: 4px;
  cursor: pointer; display: none;
}
:root[data-mode="story"] .story-exit { display: inline-block; }

/* === FONT-SIZE PRESETS === */
:root[data-font-size="compact"] {
  --fs-base: 14px;
  --fs-title: 32px;
  --fs-h2: 10px;
  --fs-stat: 28px;
  --fs-meta: 9.5px;
  --fs-toc: 12px;
  --fs-toc-id: 9.5px;
  --fs-margin: 12px;
  --fs-intent-title: 17px;
  --fs-check-desc: 13px;
}
:root[data-font-size="default"] {
  --fs-base: 17px;
  --fs-title: 40px;
  --fs-h2: 11px;
  --fs-stat: 36px;
  --fs-meta: 10.5px;
  --fs-toc: 14px;
  --fs-toc-id: 11px;
  --fs-margin: 14px;
  --fs-intent-title: 19px;
  --fs-check-desc: 14.5px;
}
:root[data-font-size="large"] {
  --fs-base: 19px;
  --fs-title: 46px;
  --fs-h2: 13px;
  --fs-stat: 40px;
  --fs-meta: 12px;
  --fs-toc: 16px;
  --fs-toc-id: 12.5px;
  --fs-margin: 16px;
  --fs-intent-title: 22px;
  --fs-check-desc: 16px;
}

/* === STYLE PRESETS === */

/* terminal: monospace everywhere, hard borders, no shadow, dense */
:root[data-style="terminal"] {
  --paper-shadow: none;
}
:root[data-style="terminal"] body,
:root[data-style="terminal"] .spec-title,
:root[data-style="terminal"] .stat-value,
:root[data-style="terminal"] .intent-title,
:root[data-style="terminal"] .check-desc,
:root[data-style="terminal"] .ac-body div,
:root[data-style="terminal"] .pinned-quote,
:root[data-style="terminal"] .spec-lede {
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}
:root[data-style="terminal"] .spec-title { font-size: 22px; letter-spacing: 0; font-weight: 600; }
:root[data-style="terminal"] .stat-value { font-size: 26px; }
:root[data-style="terminal"] .intent-title { font-size: 14px; font-weight: 600; }
:root[data-style="terminal"] .paper { padding: 32px; border: 1px solid var(--hairline); border-radius: 0; }
:root[data-style="terminal"] hr.hairline { margin: 32px 0; }
:root[data-style="terminal"] .intent-card { border-radius: 0; }
:root[data-style="terminal"] .gw-col, :root[data-style="terminal"] .ac-item, :root[data-style="terminal"] .mermaid-frame { border-radius: 0; }
:root[data-style="terminal"] .check-desc { font-size: 12.5px; }
:root[data-style="terminal"] .spec-lede { font-size: 12.5px; }

/* notebook: clean sans-serif, dense, minimal shadows */
:root[data-style="notebook"] body,
:root[data-style="notebook"] .spec-title,
:root[data-style="notebook"] .intent-title,
:root[data-style="notebook"] .check-desc,
:root[data-style="notebook"] .stat-value,
:root[data-style="notebook"] .ac-body div,
:root[data-style="notebook"] .pinned-quote,
:root[data-style="notebook"] .spec-lede {
  font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif !important;
}
:root[data-style="notebook"] .paper { padding: 40px 32px; border: 1px solid var(--hairline); }
:root[data-style="notebook"] .spec-title { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
:root[data-style="notebook"] .intent-title { font-size: 15px; font-weight: 600; }
:root[data-style="notebook"] .check-desc { font-size: 13.5px; }
:root[data-style="notebook"] .stat-value { font-size: 28px; font-weight: 600; }
:root[data-style="notebook"] .spec-lede { font-size: 14px; line-height: 1.55; }

/* brutalist: system-ui, hard borders, no transitions, no rounding, no shadows */
:root[data-style="brutalist"] {
  --paper-shadow: none;
  --hairline: #000000;
  --hairline-strong: #000000;
}
:root[data-style="brutalist"][data-theme="dark"] {
  --hairline: #ffffff;
  --hairline-strong: #ffffff;
}
:root[data-style="brutalist"] body,
:root[data-style="brutalist"] .spec-title,
:root[data-style="brutalist"] .intent-title,
:root[data-style="brutalist"] .check-desc,
:root[data-style="brutalist"] .stat-value,
:root[data-style="brutalist"] .ac-body div,
:root[data-style="brutalist"] .pinned-quote,
:root[data-style="brutalist"] .spec-lede {
  font-family: ui-monospace, 'Courier New', monospace !important;
}
:root[data-style="brutalist"] * { border-radius: 0 !important; transition: none !important; }
:root[data-style="brutalist"] .paper { border: 2px solid var(--hairline); padding: 40px; }
:root[data-style="brutalist"] .intent-card { border-width: 2px; }
:root[data-style="brutalist"] .gw-col { border-width: 2px; }
:root[data-style="brutalist"] .chip, :root[data-style="brutalist"] .copy-btn,
:root[data-style="brutalist"] .toolbar-actions button,
:root[data-style="brutalist"] .toolbar-actions select { border-width: 2px; border-radius: 0; }
:root[data-style="brutalist"] .spec-title { font-size: 32px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
:root[data-style="brutalist"] .intent-title { font-size: 14px; font-weight: 700; text-transform: uppercase; }
:root[data-style="brutalist"] .stat-value { font-size: 30px; font-weight: 700; }
:root[data-style="brutalist"] .scroll-rail-top { height: 4px; }
:root[data-style="brutalist"] hr.hairline { border-top-width: 2px; }
:root[data-style="brutalist"] .spec-lede { font-size: 13px; }

/* === SCROLL-TRIGGERED FADE-UP === */
.fade-up { opacity: 0; transform: translateY(12px); transition: opacity 500ms ease-out, transform 500ms ease-out; }
.fade-up.in-view { opacity: 1; transform: translateY(0); }
@media (prefers-reduced-motion: reduce) { .fade-up { opacity: 1; transform: none; transition: none; } }

/* === HASH-ON-HOVER ANCHORS === */
.anchor-link {
  text-decoration: none; color: inherit;
  position: relative;
}
.anchor-link::after {
  content: "#";
  position: absolute; right: -1.4em; top: 0;
  color: var(--accent); opacity: 0;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.7em;
  transition: opacity 100ms ease;
  pointer-events: none;
}
.anchor-link:hover::after, .anchor-link:focus::after { opacity: 0.55; }

/* === MARGINALIA CALLOUTS === */
.margin-block {
  border-top: none;
  background: var(--accent-faint);
  border-left: 2px solid var(--accent);
  padding: 14px 16px 16px;
  border-radius: 2px;
}
.margin-block + .margin-block { margin-top: 16px; }
.margin-block.callout-pinned { border-left-color: var(--accent); background: color-mix(in oklab, var(--accent) 6%, var(--paper)); }
.margin-block.callout-spine { border-left-color: var(--ink-muted); background: color-mix(in oklab, var(--ink-muted) 5%, var(--paper)); }
.margin-block.callout-info { border-left-color: var(--accent-soft); background: var(--accent-faint); }
.margin-block.callout-info p { line-height: 1.7; }
.margin-block.callout-info kbd { color: var(--ink-muted); background: var(--paper); margin: 0 1px; }

/* --- top scroll-progress bar --- */
.scroll-rail-top {
  position: fixed; top: 0; left: 0; right: 0; height: 2px;
  background: transparent; z-index: 100;
  pointer-events: none;
}
.scroll-rail-top::before {
  content: ""; display: block; height: 100%;
  width: var(--scroll-pct, 0%);
  background: var(--accent);
  transition: width 80ms linear;
}

/* --- spotlight cursor: CSS-driven for zero JS-side lag --- */
.spotlight {
  position: fixed; pointer-events: none; z-index: 1;
  width: 520px; height: 520px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--spotlight) 0%, transparent 62%);
  left: var(--mx, -9999px);
  top: var(--my, -9999px);
  transform: translate3d(-50%, -50%, 0);
  will-change: left, top;
  opacity: 1;
  mix-blend-mode: multiply;
  transition: opacity 200ms ease;
}
:root[data-theme="dark"] .spotlight { mix-blend-mode: screen; }
.spotlight.off { opacity: 0; }

/* --- toolbar --- */
.toolbar {
  position: sticky; top: 2px; z-index: 40;
  display: flex; align-items: center; gap: 12px;
  padding: 12px 24px;
  background: color-mix(in oklab, var(--bg) 88%, transparent);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--hairline);
}
.brand {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.18em;
  color: var(--ink-muted);
  margin-right: 16px;
  user-select: none;
}
.brand strong { color: var(--accent); font-weight: 600; }

.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.chip {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-muted);
  padding: 5px 10px;
  border: 1px solid var(--hairline-strong);
  background: transparent;
  border-radius: 999px;
  cursor: pointer;
  transition: all 150ms ease;
}
.chip:hover { color: var(--ink); border-color: var(--accent-soft); }
.chip[aria-pressed="true"] {
  color: var(--accent);
  border-color: var(--accent);
}

.toolbar-actions { display: flex; gap: 6px; margin-left: auto; align-items: center; }
.toolbar-actions button, .toolbar-actions .kbd-hint, .toolbar-actions .ghost-btn {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  padding: 5px 10px;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  color: var(--ink-muted);
  cursor: pointer;
  transition: all 150ms ease;
  border-radius: 4px;
}
.toolbar-actions button:hover, .toolbar-actions .ghost-btn:hover { color: var(--ink); border-color: var(--accent-soft); }
.toolbar-actions button[aria-pressed="true"], .toolbar-actions .ghost-btn[aria-pressed="true"] {
  color: var(--accent); border-color: var(--accent);
}
.select-wrap {
  position: relative; display: inline-flex;
}
.select-wrap select {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  padding: 5px 26px 5px 10px;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  color: var(--ink-muted);
  cursor: pointer;
  border-radius: 4px;
  appearance: none;
  -webkit-appearance: none;
  outline: none;
}
.select-wrap select:hover { color: var(--ink); border-color: var(--accent-soft); }
.select-wrap::after {
  content: "▾";
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  pointer-events: none;
  font-size: 9px;
  color: var(--ink-faint);
}
.kbd-hint {
  display: inline-flex; gap: 6px; align-items: center;
  cursor: pointer;
}
.kbd-hint kbd {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  padding: 1px 5px;
  border: 1px solid var(--hairline-strong);
  border-radius: 3px;
  color: var(--accent);
  background: var(--accent-faint);
}

/* --- 3-column layout --- */
.layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 240px;
  gap: 32px;
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px 24px 96px;
  align-items: start;
}
@media (max-width: 1100px) {
  .layout { grid-template-columns: 200px minmax(0, 1fr); }
  .marginalia { display: none; }
}
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; gap: 16px; padding: 16px; }
  .toc-rail { display: none; }
}

/* --- TOC rail --- */
.toc-rail {
  position: sticky; top: 96px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  padding-right: 8px;
}
.toc-rail-progress {
  position: relative;
  border-left: 1px solid var(--hairline);
  padding-left: 14px;
}
.toc-rail-progress::before {
  content: "";
  position: absolute; left: -1px; top: 0;
  width: 1px;
  height: var(--scroll-pct, 0%);
  background: var(--accent);
}
.toc-list {
  list-style: none; padding: 0; margin: 0;
}
.toc-list li.hidden { display: none; }
.toc-list a {
  display: grid;
  grid-template-columns: 14px 44px 1fr;
  gap: 10px;
  padding: 7px 6px;
  text-decoration: none;
  color: var(--ink-muted);
  align-items: baseline;
  border-radius: 3px;
  font-size: var(--fs-toc, 14px);
  line-height: 1.4;
  transition: background 100ms ease, color 100ms ease;
}
.toc-list a:hover { background: var(--accent-faint); color: var(--ink); }
.toc-list .toc-glyph { color: var(--ink-faint); font-size: 9px; }
.toc-list li[data-status="done"] .toc-glyph { color: var(--pass); }
.toc-list li[data-status="in_progress"] .toc-glyph { color: var(--accent); }
.toc-list li[data-status="paused"] .toc-glyph { color: var(--warn); }
.toc-list .toc-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: var(--fs-toc-id, 11px);
  color: var(--ink-faint);
  text-transform: uppercase;
}
.toc-list .toc-title { color: inherit; font-size: var(--fs-toc, 14px); }
.toc-rail-progress > div:first-child {
  font-size: 11px !important;
}
.toc-list li.is-current a {
  background: var(--accent-faint);
  color: var(--ink);
}
.toc-list li.is-current .toc-id, .toc-list li.is-current .toc-title { color: var(--accent); }

/* --- paper --- */
.paper {
  background: var(--paper);
  border-radius: 2px;
  box-shadow: var(--paper-shadow);
  padding: 56px 48px;
  min-width: 0;
}
@media (min-width: 800px) {
  .paper { padding: 80px 64px; }
}

.measure { max-width: 640px; margin: 0 auto; }
.measure-wide { max-width: 760px; margin: 0 auto; }

.meta {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
}
.meta-strong { color: var(--accent); font-weight: 500; }
.sep { color: var(--ink-faint); margin: 0 8px; }

.spec-header { margin-bottom: 0; }
.spec-meta { margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 8px 0; }
.spec-title {
  font-family: 'EB Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 40px;
  line-height: 1.12;
  letter-spacing: -0.012em;
  color: var(--ink);
  margin: 0 0 12px 0;
}
.spec-lede {
  font-size: 17px;
  line-height: 1.6;
  color: var(--ink-muted);
}

hr.hairline {
  border: none;
  border-top: 1px solid var(--hairline);
  margin: 56px 0;
}

h2.section-h {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  font-weight: 600;
  color: var(--ink-muted);
  margin: 0 0 28px 0;
  display: flex; align-items: center; gap: 10px;
}
h2.section-h::after {
  content: "";
  flex: 1; height: 1px;
  background: var(--hairline);
}

/* --- stats --- */
.stats {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 32px;
  margin-bottom: 32px;
}
@media (max-width: 700px) { .stats { grid-template-columns: 1fr; gap: 16px; } }
.stat-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
  margin-bottom: 8px;
}
.stat-value {
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 36px;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  line-height: 1;
  font-weight: 500;
}
.stat-value .frac { color: var(--ink-faint); font-size: 26px; font-weight: 400; }
.stat-sub {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--ink-faint);
  margin-top: 6px;
}

.budget-meter { width: 100%; }
.bar-track {
  width: 100%; height: 3px; background: var(--hairline);
  overflow: hidden; margin-top: 6px;
}
.bar-fill { height: 100%; transition: width 200ms ease; }
.bar-ok { background: var(--accent); }
.bar-warn { background: var(--warn); }
.bar-danger { background: var(--fail); }

/* --- phase gateway --- */
.gateway {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 800px) { .gateway { grid-template-columns: 1fr 1fr; } }
.gw-col {
  border: 1px solid var(--hairline);
  border-radius: 2px;
  padding: 14px;
  background: var(--paper);
  position: relative;
  overflow: hidden;
}
.gw-col[data-phase="implement"] { border-color: var(--pass); }
.gw-col[data-phase="tasks"] { border-color: var(--accent); }
.gw-col[data-phase="plan"] { border-color: var(--accent-soft); }
.gw-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 6px;
}
.gw-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-muted); font-weight: 600;
}
.gw-col[data-phase="implement"] .gw-label { color: var(--pass); }
.gw-col[data-phase="tasks"] .gw-label { color: var(--accent); }
.gw-count {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px; font-variant-numeric: tabular-nums;
  color: var(--ink-faint);
}
.gw-hint {
  font-size: 12px; color: var(--ink-faint);
  margin-bottom: 10px; line-height: 1.4;
  font-style: italic;
}
.gw-items { display: flex; flex-direction: column; gap: 4px; }
.gw-item {
  display: flex; gap: 8px; align-items: baseline;
  font-size: 12.5px;
  color: var(--ink-muted);
  text-decoration: none;
  padding: 3px 0;
  border-bottom: 1px dashed var(--hairline);
  transition: color 150ms ease;
}
.gw-item:hover { color: var(--accent); }
.gw-item:last-child { border-bottom: none; }
.gw-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; color: var(--ink-faint);
  text-transform: uppercase;
  flex-shrink: 0;
}
.gw-title { font-size: 12.5px; }
.gw-empty { color: var(--ink-faint); font-style: italic; font-size: 12px; }
.gw-paused {
  margin-top: 12px; padding: 10px 14px;
  border: 1px dashed var(--warn); border-radius: 2px;
  display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
}

/* --- intent cards --- */
.intent-list { display: flex; flex-direction: column; gap: 8px; }
.intent-card {
  border: 1px solid var(--hairline);
  border-radius: 2px;
  background: var(--paper);
  scroll-margin-top: 96px;
  transition: opacity 200ms ease, border-color 150ms ease;
}
.intent-card:hover { border-color: var(--hairline-strong); }
.intent-card.hidden { display: none; }
.intent-summary {
  display: grid;
  grid-template-columns: 48px 1fr auto auto auto;
  gap: 16px;
  padding: 16px 18px;
  cursor: pointer;
  align-items: center;
  user-select: none;
  outline: none;
}
.intent-summary:focus-visible { box-shadow: inset 0 0 0 2px var(--accent); }
.intent-num {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; tabular-nums;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.intent-headline { min-width: 0; }
.intent-title {
  font-family: 'EB Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 19px;
  color: var(--ink);
  margin: 0 0 6px 0;
  white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.intent-meta {
  display: flex; flex-wrap: wrap; gap: 0; align-items: center;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--ink-faint);
}
.intent-meta > * { margin-right: 12px; }
.intent-meta > *:last-child { margin-right: 0; }
.phase-pill {
  padding: 2px 8px;
  border: 1px solid var(--hairline-strong);
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 600;
}
.phase-pill.phase-implement { color: var(--pass); border-color: var(--pass); }
.phase-pill.phase-tasks { color: var(--accent); border-color: var(--accent); }
.phase-pill.phase-plan { color: var(--accent-soft); border-color: var(--accent-soft); }
.phase-pill.phase-paused { color: var(--warn); border-color: var(--warn); }
.status-open { color: var(--ink-faint); }
.status-in_progress { color: var(--accent); }
.status-done { color: var(--pass); }
.status-paused { color: var(--warn); }

.intent-counters {
  text-align: right;
  font-family: 'EB Garamond', Georgia, serif;
}
.counter-num {
  font-size: 22px; line-height: 1;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.counter-frac { color: var(--ink-faint); font-size: 16px; font-weight: 400; }
.counter-label {
  display: block; margin-top: 2px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px; text-transform: uppercase; letter-spacing: 0.16em;
  color: var(--ink-faint);
}
.copy-btn {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  padding: 4px 8px;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  color: var(--ink-faint);
  cursor: pointer;
  transition: all 100ms ease;
  border-radius: 3px;
}
.copy-btn:hover { color: var(--accent); border-color: var(--accent); }
.copy-id { background: var(--accent-faint); color: var(--accent); border-color: var(--accent-faint); }
.copy-id:hover { background: var(--accent); color: white; }
.chevron {
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 22px;
  color: var(--ink-faint);
  transition: transform 200ms ease;
  display: inline-block;
}
.chevron.open { transform: rotate(90deg); color: var(--accent); }

.intent-detail {
  border-top: 1px solid var(--hairline);
  overflow: hidden;
}
.intent-detail-inner { padding: 14px 18px 18px 82px; }
.checks {
  list-style: none; padding: 0; margin: 0;
  display: flex; flex-direction: column; gap: 10px;
}
.check-item {
  display: grid;
  grid-template-columns: 16px 1fr;
  gap: 12px;
}
.check-glyph {
  font-size: 11px;
  padding-top: 6px;
}
.glyph-pass { color: var(--pass); }
.glyph-fail { color: var(--fail); }
.glyph-pending { color: var(--ink-faint); }
.check-head { line-height: 1.5; margin-bottom: 4px; }
.check-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--ink-faint);
  margin-right: 8px;
}
.check-desc { color: var(--ink); font-size: 14.5px; }
.cmd-row { display: flex; gap: 6px; }
.cmd, .inline-cmd {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  background: var(--accent-faint);
  color: var(--ink-muted);
  padding: 4px 8px;
  border: 1px solid var(--hairline);
  word-break: break-all;
  white-space: pre-wrap;
  border-radius: 2px;
}
.cmd { flex: 1; }
.inline-cmd { display: inline; padding: 1px 4px; font-size: 10.5px; }
.cmd-manual { color: var(--ink-faint); font-style: italic; background: transparent; }

details.audit-failure {
  margin-top: 14px;
  padding-left: 14px;
  border-left: 2px solid var(--fail);
}
details.audit-failure summary {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--fail);
  cursor: pointer;
  list-style: none;
}
details.audit-failure summary::before {
  content: "▸ "; color: var(--ink-faint); font-size: 10px;
}
details.audit-failure[open] summary::before { content: "▾ "; }
details.audit-failure pre {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--ink-muted);
  white-space: pre-wrap;
  margin: 8px 0 0 0;
}

/* --- acceptance criteria --- */
.ac-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 16px; }
.ac-item {
  display: grid; grid-template-columns: 16px 1fr; gap: 14px;
  padding: 14px 18px;
  border-left: 2px solid var(--hairline);
  background: var(--paper);
}
.ac-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-faint);
  margin-bottom: 6px;
}
.ac-body div { line-height: 1.55; font-size: 14px; }
.ac-kw {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--accent);
  font-weight: 600;
  margin-right: 8px;
  display: inline-block;
  width: 50px;
}

/* --- decision log --- */
.decision-list { list-style: none; padding: 0; margin: 0; }
.decision-item {
  display: grid;
  grid-template-columns: 110px 70px 140px 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--hairline);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  align-items: baseline;
}
.decision-item:last-child { border-bottom: none; }
.decision-kind { color: var(--accent); text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; }
.decision-intent { color: var(--ink); }
.decision-ts { color: var(--ink-faint); font-variant-numeric: tabular-nums; }
.decision-detail { color: var(--ink-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* --- mermaid --- */
.mermaid-frame {
  position: relative; padding: 16px;
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: 2px;
  cursor: zoom-in;
  transition: border-color 150ms ease;
}
.mermaid-frame:hover { border-color: var(--accent-soft); }
.mermaid-frame::after {
  content: "click to zoom";
  position: absolute; top: 8px; right: 12px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-faint);
  opacity: 0; transition: opacity 150ms ease;
  pointer-events: none;
}
.mermaid-frame:hover::after { opacity: 1; }
.mermaid { display: flex; justify-content: center; }
.mermaid svg { max-width: 100%; height: auto; }

dialog.zoom-dlg {
  width: 90vw; height: 90vh;
  max-width: none; max-height: none;
  border: none; padding: 0;
  background: var(--paper);
  box-shadow: 0 30px 60px rgba(0,0,0,0.3);
  border-radius: 2px;
}
dialog.zoom-dlg::backdrop {
  background: color-mix(in oklab, var(--bg) 80%, transparent);
  backdrop-filter: blur(8px);
}
.zoom-body { width: 100%; height: 100%; padding: 24px; overflow: hidden; }
.zoom-body svg { width: 100%; height: 100%; }
.zoom-close {
  position: absolute; top: 12px; right: 12px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  padding: 6px 10px;
  background: var(--paper); border: 1px solid var(--hairline-strong);
  cursor: pointer; border-radius: 3px;
}

/* --- events --- */
.events { width: 100%; border-collapse: collapse; }
.events tr { border-bottom: 1px solid var(--hairline); }
.events tr:last-child { border-bottom: none; }
.events td {
  padding: 8px 12px 8px 0;
  vertical-align: top;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
}
.events .ev-time { color: var(--ink-faint); width: 80px; font-variant-numeric: tabular-nums; }
.events .ev-kind {
  text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink); width: 160px;
}
.events .ev-detail { color: var(--ink-muted); }
.empty { color: var(--ink-faint); font-style: italic; }

/* --- marginalia --- */
.marginalia {
  position: sticky; top: 96px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}
.margin-block {
  border-top: 1px solid var(--hairline);
  padding-top: 16px;
  margin-bottom: 32px;
}
.margin-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.16em;
  color: var(--ink-faint);
  margin-bottom: 10px;
}
.margin-block p, .margin-block li { font-size: var(--fs-margin, 14px); line-height: 1.6; color: var(--ink-muted); margin: 0 0 8px 0; }
.margin-block ul { padding-left: 14px; margin: 0; }
.margin-block .pinned-quote {
  font-style: italic;
  color: var(--ink);
  font-size: var(--fs-margin, 14px);
  line-height: 1.55;
  white-space: pre-wrap;
  font-family: 'EB Garamond', Georgia, serif;
}
.margin-label {
  font-size: 10.5px !important;
}

/* --- command palette --- */
.palette-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: color-mix(in oklab, var(--bg) 78%, transparent);
  backdrop-filter: blur(8px);
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 18vh;
}
.palette {
  width: min(640px, 92vw);
  background: var(--paper);
  border-radius: 6px;
  box-shadow: 0 30px 60px rgba(0,0,0,0.25);
  overflow: hidden;
}
.palette input {
  width: 100%;
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 18px;
  padding: 18px 20px;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--hairline);
  color: var(--ink);
  outline: none;
}
.palette input::placeholder { color: var(--ink-faint); }
.palette-list { list-style: none; padding: 6px; margin: 0; max-height: 50vh; overflow-y: auto; }
.palette-item {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 10px; align-items: baseline;
  padding: 9px 12px;
  cursor: pointer;
  border-radius: 3px;
  font-size: 14px;
  color: var(--ink);
}
.palette-item.is-active { background: var(--accent-faint); color: var(--accent); }
.palette-item .pi-kind {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-faint);
}
.palette-item.is-active .pi-kind { color: var(--accent); }
.palette-foot {
  border-top: 1px solid var(--hairline);
  padding: 8px 14px;
  display: flex; gap: 16px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--ink-faint);
}
.palette-foot kbd {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9.5px;
  padding: 1px 5px;
  border: 1px solid var(--hairline-strong);
  border-radius: 3px;
  background: var(--accent-faint);
  color: var(--accent);
  margin-right: 4px;
}

/* --- toasts --- */
#toasts {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  z-index: 90;
  display: flex; flex-direction: column; gap: 8px;
  pointer-events: none;
}
.toast {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  background: var(--paper);
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 8px 14px;
  border-radius: 2px;
  box-shadow: var(--paper-shadow);
  animation: toast-in 200ms ease, toast-out 200ms ease 1.6s forwards;
}
@keyframes toast-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes toast-out {
  to { opacity: 0; transform: translateY(-8px); }
}

footer.bottom {
  text-align: center;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
  margin-top: 32px;
}

/* --- print --- */
@media print {
  .toolbar, .toc-rail, .marginalia, .palette-overlay, #toasts,
  .copy-btn, .scroll-rail-top, .spotlight, .chevron, .mermaid-frame::after { display: none !important; }
  body { background: white; color: black; }
  .layout { display: block; padding: 0; max-width: none; }
  .paper { box-shadow: none; padding: 0; }
  .intent-card { page-break-inside: avoid; opacity: 1 !important; border: 1px solid #ccc; margin-bottom: 12px; }
  .intent-card.hidden { display: block !important; }
  .intent-detail { display: block !important; height: auto !important; overflow: visible !important; }
  details { open: ""; }
  details summary { display: none; }
  details > *:not(summary) { display: block !important; }
}
"""


JS = r"""
document.addEventListener('alpine:init', () => {
  Alpine.data('app', () => ({
    filter: 'all',
    search: '',
    theme: document.documentElement.dataset.theme || 'paper',
    style: document.documentElement.dataset.style || 'editorial',
    fontSize: document.documentElement.dataset.fontSize || 'default',
    mode: 'normal',
    spotlightOn: true,
    paletteOpen: false,
    paletteQuery: '',
    paletteIdx: 0,
    paletteAll: window.__GPR_PALETTE__ || [],
    lsKey: 'gpr:viewer:' + (document.documentElement.dataset.planId || 'default'),

    init() {
      const stored = JSON.parse(localStorage.getItem(this.lsKey) || '{}');
      Object.assign(this, stored);
      this.applyTheme();
      this.applyStyle();
      this.applyFontSize();
      this.applyMode();
      this.applyFilter();
      this.bindScroll();
      this.bindIntersection();
      this.bindKeyboard();
      this.bindCopy();
      this.bindMermaidZoom();
      this.bindSpotlight();
      this.bindFadeUp();
      this.bindAnchors();
    },

    persist() {
      localStorage.setItem(this.lsKey, JSON.stringify({
        filter: this.filter,
        search: this.search,
        theme: this.theme,
        style: this.style,
        fontSize: this.fontSize,
        mode: this.mode,
        spotlightOn: this.spotlightOn,
      }));
    },

    setStyle(s) { this.style = s; this.applyStyle(); this.persist(); },
    applyStyle() { document.documentElement.dataset.style = this.style; },
    setFontSize(f) { this.fontSize = f; this.applyFontSize(); this.persist(); },
    applyFontSize() { document.documentElement.dataset.fontSize = this.fontSize; },
    setMode(m) { this.mode = m; this.applyMode(); this.persist(); this.toast(m === 'story' ? 'story mode · press s to exit' : 'normal mode'); },
    applyMode() { document.documentElement.dataset.mode = this.mode; },
    toggleMode() { this.setMode(this.mode === 'story' ? 'normal' : 'story'); },
    toggleSpotlight() {
      this.spotlightOn = !this.spotlightOn;
      const el = document.querySelector('.spotlight');
      if (el) el.classList.toggle('off', !this.spotlightOn);
      this.persist();
      this.toast(this.spotlightOn ? 'spotlight on' : 'spotlight off');
    },

    setFilter(f) { this.filter = f; this.applyFilter(); this.persist(); },

    applyFilter() {
      const q = (this.search || '').trim().toLowerCase();
      const f = this.filter;
      document.querySelectorAll('.intent-card').forEach(s => {
        const matchesStatus = f === 'all' || s.dataset.status === f;
        const matchesSearch = !q ||
          s.dataset.id.toLowerCase().includes(q) ||
          s.dataset.title.includes(q);
        s.classList.toggle('hidden', !(matchesStatus && matchesSearch));
      });
      document.querySelectorAll('.toc-list li[data-toc-id]').forEach(li => {
        const sec = document.getElementById('intent-' + li.dataset.tocId);
        li.classList.toggle('hidden', sec && sec.classList.contains('hidden'));
      });
    },

    setTheme(t) { this.theme = t; this.applyTheme(); this.persist(); },

    applyTheme() { document.documentElement.dataset.theme = this.theme; },

    /* --- scroll progress rail --- */
    bindScroll() {
      const onScroll = () => {
        const h = document.documentElement.scrollHeight - window.innerHeight;
        const pct = h > 0 ? Math.max(0, Math.min(100, (window.scrollY / h) * 100)) : 0;
        document.documentElement.style.setProperty('--scroll-pct', pct.toFixed(2) + '%');
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    },

    /* --- TOC current-section --- */
    bindIntersection() {
      if (!('IntersectionObserver' in window)) return;
      const tocItems = document.querySelectorAll('.toc-list li[data-toc-id]');
      const obs = new IntersectionObserver(entries => {
        entries.forEach(en => {
          if (!en.isIntersecting) return;
          const id = en.target.dataset.id;
          tocItems.forEach(li => li.classList.toggle('is-current', li.dataset.tocId === id));
        });
      }, { rootMargin: '-30% 0px -60% 0px' });
      document.querySelectorAll('.intent-card').forEach(s => obs.observe(s));
    },

    /* --- copy buttons --- */
    bindCopy() {
      document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-copy]');
        if (!btn) return;
        try {
          await navigator.clipboard.writeText(btn.dataset.copy);
          this.toast('copied');
        } catch (err) {
          this.toast('copy failed');
        }
      });
    },

    /* --- toasts --- */
    toast(msg) {
      const tb = document.getElementById('toasts');
      if (!tb) return;
      const el = document.createElement('div');
      el.className = 'toast';
      el.textContent = msg;
      tb.appendChild(el);
      setTimeout(() => el.remove(), 2000);
    },

    /* --- keyboard nav + cmd-k --- */
    bindKeyboard() {
      document.addEventListener('keydown', (e) => {
        const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
        const meta = e.metaKey || e.ctrlKey;
        if (meta && e.key.toLowerCase() === 'k') { e.preventDefault(); this.openPalette(); return; }
        if (this.paletteOpen) {
          if (e.key === 'Escape') { this.closePalette(); return; }
          if (e.key === 'ArrowDown') { e.preventDefault(); this.paletteIdx = Math.min(this.paletteIdx + 1, this.paletteFiltered().length - 1); this.scrollPaletteIntoView(); return; }
          if (e.key === 'ArrowUp') { e.preventDefault(); this.paletteIdx = Math.max(this.paletteIdx - 1, 0); this.scrollPaletteIntoView(); return; }
          if (e.key === 'Enter') { e.preventDefault(); this.runPaletteItem(this.paletteFiltered()[this.paletteIdx]); return; }
          return;
        }
        if (isInput) { if (e.key === 'Escape') e.target.blur(); return; }
        if (e.key === 'Escape' && this.mode === 'story') { this.setMode('normal'); return; }
        if (e.key === '?') { e.preventDefault(); this.openPalette(); return; }
        if (e.key === '/') { e.preventDefault(); this.openPalette(); return; }
        if (e.key === 'j') { e.preventDefault(); this.jumpRel(+1); return; }
        if (e.key === 'k') { e.preventDefault(); this.jumpRel(-1); return; }
        if (e.key === 's' || e.key === 'S') { e.preventDefault(); this.toggleMode(); return; }
      });
    },

    visibleIntents() {
      return Array.from(document.querySelectorAll('.intent-card:not(.hidden)'));
    },
    currentIntentIdx() {
      const v = this.visibleIntents();
      let best = 0, bestTop = -Infinity;
      v.forEach((s, i) => {
        const top = s.getBoundingClientRect().top;
        if (top <= 120 && top > bestTop) { bestTop = top; best = i; }
      });
      return best;
    },
    jumpRel(d) {
      const v = this.visibleIntents();
      if (!v.length) return;
      const idx = Math.max(0, Math.min(v.length - 1, this.currentIntentIdx() + d));
      const t = v[idx];
      t.scrollIntoView({ behavior: 'smooth', block: 'start' });
      history.replaceState(null, '', '#' + t.id);
    },

    /* --- palette --- */
    openPalette() {
      this.paletteOpen = true;
      this.paletteQuery = '';
      this.paletteIdx = 0;
      this.$nextTick(() => {
        const inp = document.querySelector('.palette input');
        if (inp) inp.focus();
      });
    },
    closePalette() { this.paletteOpen = false; },
    paletteFiltered() {
      const q = (this.paletteQuery || '').trim().toLowerCase();
      if (!q) return this.paletteAll;
      return this.paletteAll.filter(it => it.label.toLowerCase().includes(q));
    },
    runPaletteItem(item) {
      if (!item) return;
      this.closePalette();
      if (item.target) {
        location.hash = item.target;
        const el = document.querySelector(item.target);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      } else if (item.action) {
        const [verb, arg] = item.action.split(':');
        if (verb === 'theme') this.setTheme(arg);
        else if (verb === 'filter') this.setFilter(arg);
        else if (verb === 'graph' && arg === 'fullscreen') this.zoomMermaid();
        else if (verb === 'spotlight' && arg === 'toggle') this.toggleSpotlight();
        else if (verb === 'style') this.setStyle(arg);
        else if (verb === 'fontsize') this.setFontSize(arg);
        else if (verb === 'mode') this.setMode(arg);
        else if (verb === 'print') window.print();
      }
    },
    scrollPaletteIntoView() {
      this.$nextTick(() => {
        const el = document.querySelector('.palette-item.is-active');
        if (el) el.scrollIntoView({ block: 'nearest' });
      });
    },

    /* --- mermaid zoom --- */
    bindMermaidZoom() {
      const frame = document.querySelector('.mermaid-frame');
      if (!frame) return;
      frame.addEventListener('click', () => this.zoomMermaid());
    },
    zoomMermaid() {
      const dlg = document.querySelector('dialog.zoom-dlg');
      if (!dlg) return;
      const src = document.querySelector('.mermaid-frame .mermaid svg');
      const body = dlg.querySelector('.zoom-body');
      body.innerHTML = '';
      if (src) body.appendChild(src.cloneNode(true));
      dlg.showModal();
      if (window.svgPanZoom && body.querySelector('svg')) {
        window.__panZoom && window.__panZoom.destroy();
        window.__panZoom = svgPanZoom(body.querySelector('svg'), {
          zoomEnabled: true, controlIconsEnabled: false,
          fit: true, center: true, minZoom: 0.5, maxZoom: 8,
        });
      }
    },

    /* --- scroll-triggered fade-up --- */
    bindFadeUp() {
      if (!('IntersectionObserver' in window)) {
        document.querySelectorAll('.fade-up').forEach(s => s.classList.add('in-view'));
        return;
      }
      const obs = new IntersectionObserver(entries => {
        entries.forEach(en => {
          if (en.isIntersecting) {
            en.target.classList.add('in-view');
            obs.unobserve(en.target);
          }
        });
      }, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });
      document.querySelectorAll('.fade-up').forEach(s => obs.observe(s));
    },

    /* --- hash-on-hover anchors: click copies link with toast --- */
    bindAnchors() {
      document.addEventListener('click', (e) => {
        const a = e.target.closest('.anchor-link');
        if (!a) return;
        e.preventDefault();
        const id = (a.getAttribute('href') || '').replace('#', '');
        if (!id) return;
        const url = location.origin + location.pathname + '#' + id;
        navigator.clipboard.writeText(url).then(() => this.toast('link copied'))
                                          .catch(() => this.toast('copy failed'));
        history.replaceState(null, '', '#' + id);
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      });
    },

    /* --- spotlight cursor: CSS variable, rAF-coalesced — direct follow, no lag --- */
    bindSpotlight() {
      const el = document.querySelector('.spotlight');
      if (!el) return;
      el.classList.toggle('off', !this.spotlightOn);
      let lastX = 0, lastY = 0, pending = false;
      const root = document.documentElement;
      window.addEventListener('pointermove', (e) => {
        lastX = e.clientX; lastY = e.clientY;
        if (!pending) {
          pending = true;
          requestAnimationFrame(() => {
            root.style.setProperty('--mx', lastX + 'px');
            root.style.setProperty('--my', lastY + 'px');
            pending = false;
          });
        }
      }, { passive: true });
    },
  }));
});
"""


HTML_SHELL = """\
<!doctype html>
<html lang="en" data-theme="{initial_theme}" data-style="{initial_style}" data-font-size="{initial_font_size}" data-plan-id="{plan_id}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.2/dist/svg-pan-zoom.min.js"></script>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{
  startOnLoad: true,
  theme: 'neutral',
  securityLevel: 'loose',
  themeVariables: {{
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: '12px',
    primaryColor: 'transparent',
    primaryBorderColor: '#1f3873',
    primaryTextColor: '#1c1917',
    lineColor: '#a8a29e',
  }}
}});
</script>
<script defer src="https://cdn.jsdelivr.net/npm/@alpinejs/collapse@3.x.x/dist/cdn.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

<style>{css}</style>
<script>window.__GPR_PALETTE__ = {palette_json};</script>
</head>
<body x-data="app">

<div class="spotlight"></div>
<div class="scroll-rail-top"></div>
<button class="story-exit" @click="setMode('normal')">exit story · esc</button>

<nav class="toolbar" role="toolbar">
  <div class="brand"><strong>gpr</strong> · {brand_proj}</div>
  <div class="chips">
    <button class="chip" :aria-pressed="filter==='all'"        @click="setFilter('all')">all</button>
    <button class="chip" :aria-pressed="filter==='open'"       @click="setFilter('open')">open</button>
    <button class="chip" :aria-pressed="filter==='in_progress'" @click="setFilter('in_progress')">in&nbsp;progress</button>
    <button class="chip" :aria-pressed="filter==='done'"       @click="setFilter('done')">done</button>
    <button class="chip" :aria-pressed="filter==='paused'"     @click="setFilter('paused')">paused</button>
  </div>
  <div class="toolbar-actions">
    <span class="kbd-hint" @click="openPalette()" title="open command palette"><kbd>⌘</kbd><kbd>K</kbd></span>
    <div class="select-wrap" title="viewer style">
      <select x-model="style" @change="setStyle(style)">
        <option value="editorial">editorial</option>
        <option value="terminal">terminal</option>
        <option value="notebook">notebook</option>
        <option value="brutalist">brutalist</option>
      </select>
    </div>
    <div class="select-wrap" title="theme">
      <select x-model="theme" @change="setTheme(theme)">
        <option value="paper">paper</option>
        <option value="sepia">sepia</option>
        <option value="dark">dark</option>
        <option value="arctic">arctic</option>
      </select>
    </div>
    <div class="select-wrap" title="font size">
      <select x-model="fontSize" @change="setFontSize(fontSize)">
        <option value="compact">compact</option>
        <option value="default">default</option>
        <option value="large">large</option>
      </select>
    </div>
    <button class="ghost-btn" :aria-pressed="spotlightOn" @click="toggleSpotlight()" title="spotlight cursor">spot</button>
    <button class="ghost-btn" @click="toggleMode()" title="story mode (S)">story</button>
    <button class="ghost-btn" @click="window.print()" title="print">print</button>
  </div>
</nav>

<div class="layout">
  <aside class="toc-rail" aria-label="contents">
    <div class="toc-rail-progress">
      <div style="font-family:'JetBrains Mono',monospace;font-size:9.5px;text-transform:uppercase;letter-spacing:0.16em;color:var(--ink-faint);margin-bottom:8px;">contents</div>
      {toc_html}
    </div>
  </aside>

  <article class="paper">
{body}
  </article>

  <aside class="marginalia">
    {marginalia}
  </aside>
</div>

<footer class="bottom">rendered by gpr render · ⌘K for palette · ? for help</footer>

<dialog class="zoom-dlg" @close="window.__panZoom && window.__panZoom.destroy()">
  <button class="zoom-close" @click="$el.closest('dialog').close()">close · esc</button>
  <div class="zoom-body"></div>
</dialog>

<template x-teleport="body">
  <div x-show="paletteOpen" x-cloak class="palette-overlay" @click.self="closePalette()">
    <div class="palette" role="dialog" aria-label="command palette">
      <input
        type="text"
        x-model="paletteQuery"
        @input="paletteIdx = 0"
        placeholder="jump to a section, intent, or run a command…">
      <ul class="palette-list">
        <template x-for="(item, idx) in paletteFiltered()" :key="(item.target||item.action)+'_'+idx">
          <li class="palette-item"
              :class="{{ 'is-active': idx === paletteIdx }}"
              @click="runPaletteItem(item)"
              @mouseenter="paletteIdx = idx">
            <span class="pi-kind" x-text="item.kind"></span>
            <span x-text="item.label"></span>
          </li>
        </template>
        <li x-show="paletteFiltered().length === 0" class="palette-item" style="color: var(--ink-faint); font-style: italic;">no matches</li>
      </ul>
      <div class="palette-foot">
        <span><kbd>↑↓</kbd> navigate</span>
        <span><kbd>↵</kbd> open</span>
        <span><kbd>esc</kbd> close</span>
      </div>
    </div>
  </div>
</template>

<div id="toasts" aria-live="polite"></div>

<script>{js}</script>
</body>
</html>
"""


def render(plan: dict[str, Any], state: dict[str, Any], gpr_dir: Path,
           project_root: Path, cfg: dict[str, Any] | None = None) -> str:
    counts: dict[str, int] = {}
    for it in plan["intents"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    total = sum(counts.values())
    done = counts.get("done", 0)
    pct = round((done / total) * 100, 1) if total else 0.0

    all_done_ids = {it["id"] for it in plan["intents"] if it["status"] == "done"}
    intents_html = "".join(
        _intent_card_html(i + 1, it, all_done_ids)
        for i, it in enumerate(plan["intents"])
    )
    dag = _intent_dag_mermaid(plan)
    toc_html = _toc_html(plan)
    palette_json = _command_palette_data(plan)

    bs = budget_mod.status(plan, state)
    bf = bs["fraction_used"] or 0.0
    bcls = "bar-danger" if bf >= 0.95 else ("bar-warn" if bf >= 0.6 else "bar-ok")
    bpct = round(bf * 100, 1)
    cost = state.get("costUsd", 0.0)
    tokens = state.get("tokensInput", 0) + state.get("tokensOutput", 0)
    wall = state.get("wallClockSeconds", 0.0)
    iteration = plan["globalState"]["iteration"]
    same_sig = plan["globalState"]["consecutiveSameSignature"]
    persona = plan.get("persona", {}).get("primary", "principal_engineer")

    pinned_text = ""
    pinned_path = gpr_dir / "Pinned.md"
    if pinned_path.exists():
        pinned_text = pinned_path.read_text(errors="replace")[:1200]

    spine_text = ""
    spine_path = gpr_dir / "Spine.md"
    if spine_path.exists():
        spine_text = spine_path.read_text(errors="replace")[:800]

    decision_log = _decision_log_html(plan, project_root)
    ac_html = _acceptance_html(plan)
    events_html = _events_html(project_root)
    phase_gw = _phase_gateway_html(plan)

    body = f"""
    <header id="section-goal" class="spec-header measure fade-up">
      <div class="meta spec-meta">
        <span>{_esc(plan["project"])}</span>
        <span class="sep">/</span>
        <span>branch · {_esc(plan["branch"])}</span>
        <span class="sep">/</span>
        <span class="meta-strong">{_esc(plan.get("status", "pursuing"))}</span>
        <span class="sep">/</span>
        <span>persona · {_esc(persona.replace("_", " "))}</span>
      </div>
      <h1 class="spec-title"><a href="#section-goal" class="anchor-link">{_esc(plan["goal"])}</a></h1>
      <p class="spec-lede">A spec lives in two states at once: a story humans read top-to-bottom, and a contract machines verify line-by-line. This page is both.</p>
    </header>

    <hr class="hairline">

    <section class="measure fade-up">
      <h2 class="section-h"><a href="#section-progress" class="anchor-link" id="section-progress">01 · progress</a></h2>
      <div class="stats">
        <div>
          <div class="stat-label">intents</div>
          <div class="stat-value">{done}<span class="frac"> / {total}</span></div>
          <div class="stat-sub">{pct}% done</div>
        </div>
        <div>
          <div class="stat-label">iteration</div>
          <div class="stat-value">{iteration}</div>
          <div class="stat-sub">same-sig · {same_sig}</div>
        </div>
        <div>
          <div class="stat-label">budget</div>
          <div class="budget-meter">
            <div class="bar-track"><div class="bar-fill {bcls}" style="width:{min(100,bpct)}%"></div></div>
            <div class="meta" style="margin-top:8px;">{bpct}% of {_esc(bs.get("binding_axis") or "—")}</div>
          </div>
        </div>
      </div>
      <div class="meta" style="margin-top: 18px;">
        cost · ${_esc(round(cost, 2))}
        <span class="sep">·</span>
        tokens · {_esc(tokens)}
        <span class="sep">·</span>
        wall · {_esc(round(wall))}s
      </div>
    </section>

    <hr class="hairline">

    <section id="section-phases" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-phases" class="anchor-link">02 · phase gateway</a></h2>
      {phase_gw}
    </section>

    <hr class="hairline">

    <section id="section-graph" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-graph" class="anchor-link">03 · intent graph</a></h2>
      <div class="mermaid-frame">
        <pre class="mermaid">{_esc(dag)}</pre>
      </div>
    </section>

    <hr class="hairline">

    <section id="section-intents" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-intents" class="anchor-link">04 · intents</a></h2>
      <div class="intent-list">
        {intents_html}
      </div>
    </section>

    <hr class="hairline">

    <section id="section-ac" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-ac" class="anchor-link">05 · acceptance criteria · given/when/then</a></h2>
      {ac_html}
    </section>

    <hr class="hairline">

    <section id="section-decisions" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-decisions" class="anchor-link">06 · decision log</a></h2>
      {decision_log}
    </section>

    <hr class="hairline">

    <section id="section-events" class="measure-wide fade-up">
      <h2 class="section-h"><a href="#section-events" class="anchor-link">07 · recent events</a></h2>
      {events_html}
    </section>
    """

    marginalia = ""
    if pinned_text.strip():
        marginalia += (
            '<div class="margin-block callout-pinned">'
            '<div class="margin-label">pinned · invariants</div>'
            f'<div class="pinned-quote">{_esc(pinned_text.strip())}</div>'
            '</div>'
        )
    if spine_text.strip():
        marginalia += (
            '<div class="margin-block callout-spine">'
            '<div class="margin-label">spine · memory</div>'
            f'<div class="pinned-quote">{_esc(spine_text.strip())}</div>'
            '</div>'
        )
    marginalia += (
        '<div class="margin-block callout-info">'
        '<div class="margin-label">how to read this</div>'
        '<p>Press <kbd style="font-family:JetBrains Mono;font-size:10px;padding:1px 5px;border:1px solid currentColor;border-radius:3px">S</kbd> for story mode · '
        '<kbd style="font-family:JetBrains Mono;font-size:10px;padding:1px 5px;border:1px solid currentColor;border-radius:3px">⌘K</kbd> palette · '
        '<kbd style="font-family:JetBrains Mono;font-size:10px;padding:1px 5px;border:1px solid currentColor;border-radius:3px">J</kbd>/<kbd style="font-family:JetBrains Mono;font-size:10px;padding:1px 5px;border:1px solid currentColor;border-radius:3px">K</kbd> walk intents · '
        'click any heading to copy its link.</p>'
        '</div>'
    )

    plan_id = (
        plan.get("project", "default") + "|"
        + (plan.get("createdAt", "") or "")
    )
    cfg = cfg or {}
    initial_style = cfg.get("viewer.style", "editorial")
    initial_theme = cfg.get("viewer.theme", "paper")
    initial_font_size = cfg.get("viewer.font_size", "default")
    initial_spotlight = "true" if cfg.get("viewer.spotlight", True) else "false"
    initial_palette = "true" if cfg.get("viewer.palette", True) else "false"
    return HTML_SHELL.format(
        title=f"{_esc(plan['project'])} · gpr",
        plan_id=_esc(plan_id),
        css=CSS,
        js=JS,
        body=body,
        toc_html=toc_html,
        marginalia=marginalia,
        palette_json=palette_json,
        brand_proj=_esc(plan["project"]),
        initial_style=_esc(initial_style),
        initial_theme=_esc(initial_theme),
        initial_font_size=_esc(initial_font_size),
        initial_spotlight=initial_spotlight,
        initial_palette=initial_palette,
    )
