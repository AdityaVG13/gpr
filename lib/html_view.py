"""Render the Plan as a self-contained, interactive HTML page.

Single-file output. Tailwind via CDN for utility classes, Mermaid via CDN
for the intent DAG, vanilla JS for everything else: sticky TOC with
IntersectionObserver, hash-based deep linking, filter chips with
localStorage, copy-to-clipboard on every verifyCmd, keyboard navigation
(j/k/?//), Mermaid current-intent highlight, per-check details
expansion, theme toggle (paper/sepia/dark), print stylesheet.

Cleanroom CSS — editorial serif body, mono metadata, paper card,
cobalt accent, hairline rules.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .state import budget as budget_mod
from .state import events as events_mod


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def _completion_glyph(intent: dict[str, Any]) -> str:
    """Aggregate glyph for an intent's completion state."""
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


def _check_glyph(intent: dict[str, Any], check_id: str) -> str:
    proofs = {p.get("checkId"): p for p in intent.get("proofs", [])}
    if check_id in proofs:
        return '<span class="glyph glyph-pass" aria-label="proven">●</span>'
    failures = [
        f for f in intent.get("auditFailures", [])
        for d in f.get("audit", {}).get("details", [])
        if d.get("checkId") == check_id and d.get("result") == "fail"
    ]
    if failures:
        return '<span class="glyph glyph-fail" aria-label="audit failed">●</span>'
    return '<span class="glyph glyph-pending" aria-label="unchecked">○</span>'


def _intent_dag_mermaid(plan: dict[str, Any]) -> str:
    lines = ["graph LR"]
    for it in plan["intents"]:
        node_id = _esc(it["id"])
        title = _esc(it["title"])[:34]
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


def _budget_meter(plan: dict[str, Any], state: dict[str, Any]) -> str:
    bs = budget_mod.status(plan, state)
    f = bs["fraction_used"] or 0.0
    pct = round(f * 100, 1)
    if f >= 0.95:
        cls = "bar-danger"
    elif f >= 0.6:
        cls = "bar-warn"
    else:
        cls = "bar-ok"
    width = min(100, max(0, pct))
    axis = bs["binding_axis"] or "—"
    return (
        '<div class="budget-meter">'
        '<div class="meta-row">'
        f'<span class="meta">binding axis</span>'
        f'<span class="meta">{_esc(axis)}</span>'
        '</div>'
        f'<div class="bar-track"><div class="bar-fill {cls}" style="width:{width}%"></div></div>'
        f'<div class="meta-row meta-pct">{pct}%</div>'
        '</div>'
    )


def _verifycmd_block(cmd: str | None) -> str:
    if not cmd:
        return '<div class="cmd cmd-manual">manual gate</div>'
    cmd_esc = _esc(cmd)
    return (
        '<div class="cmd-row">'
        f'<code class="cmd">{cmd_esc}</code>'
        f'<button class="copy-btn" data-copy="{cmd_esc}" title="copy">copy</button>'
        '</div>'
    )


def _intent_section(idx: int, intent: dict[str, Any]) -> str:
    num = f"{idx:02d}"
    deps = ", ".join(_esc(d) for d in intent["dependsOn"]) or "—"
    checks_html = "".join(
        '<li class="check-item">'
        f'<span class="check-glyph">{_check_glyph(intent, ch["id"])}</span>'
        f'<div class="check-body">'
        f'<div class="check-head"><span class="check-id">{_esc(ch["id"])}</span> '
        f'<span class="check-desc">{_esc(ch["description"])}</span></div>'
        f'{_verifycmd_block(ch.get("verifyCmd"))}'
        '</div>'
        '</li>'
        for ch in intent.get("checks", [])
    )
    fails = intent.get("auditFailures", [])
    fail_block = ""
    if fails:
        latest = fails[-1]
        fail_block = (
            '<details class="audit-failure">'
            '<summary>last audit failure</summary>'
            f'<pre>{_esc(json.dumps(latest, indent=2)[:600])}</pre>'
            '</details>'
        )
    return (
        f'<section id="intent-{_esc(intent["id"])}" class="intent-section" '
        f'data-status="{_esc(intent["status"])}" '
        f'data-id="{_esc(intent["id"])}" '
        f'data-title="{_esc(intent["title"]).lower()}">'
        f'<div class="intent-num">{num}</div>'
        '<div class="intent-body">'
        f'<div class="intent-head">'
        f'<h3 class="intent-title">{_esc(intent["title"])}</h3>'
        f'<button class="copy-btn copy-id" data-copy="{_esc(intent["id"])}" title="copy intent id">{_esc(intent["id"])}</button>'
        f'</div>'
        f'<div class="intent-meta">'
        f'<span class="status status-{_esc(intent["status"])}">{_esc(intent["status"].replace("_", " "))}</span>'
        '<span class="sep">·</span>'
        f'<span class="meta">priority {_esc(intent["priority"])}</span>'
        '<span class="sep">·</span>'
        f'<span class="meta">depends · {_esc(deps)}</span>'
        '</div>'
        f'<ul class="checks">{checks_html}</ul>'
        f'{fail_block}'
        '</div>'
        '</section>'
    )


def _toc_block(plan: dict[str, Any]) -> str:
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


def _events_block(project_root: Path, n: int = 24) -> str:
    events = events_mod.tail(project_root, n=n)
    if not events:
        return '<p class="empty">no events yet</p>'
    rows = []
    for e in reversed(events):
        kind = _esc(e.get("kind", "?"))
        ts = e.get("t", 0)
        from datetime import datetime, timezone
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


def _intent_counts(plan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in plan["intents"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return counts


CSS = """
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
}
:root[data-theme="dark"] {
  --bg: #0f0e0c;
  --paper: #1a1815;
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
                  0 1px 4px 1px rgba(0,0,0,0.4);
}

* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: 'EB Garamond', Georgia, 'Times New Roman', serif;
  font-feature-settings: 'liga', 'calt';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
body { transition: background 200ms ease, color 200ms ease; }

.toolbar {
  position: sticky; top: 0; z-index: 40;
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px;
  background: color-mix(in oklab, var(--bg) 92%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--hairline);
}
.toolbar .chips { display: flex; gap: 4px; flex-wrap: wrap; }
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
.toolbar .search {
  flex: 1;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid var(--hairline);
  color: var(--ink);
  outline: none;
  min-width: 120px;
  max-width: 320px;
}
.toolbar .search:focus { border-color: var(--accent); }
.toolbar .actions { display: flex; gap: 4px; margin-left: auto; }
.toolbar .actions button {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em;
  padding: 5px 9px;
  background: transparent;
  border: 1px solid var(--hairline-strong);
  color: var(--ink-muted);
  cursor: pointer;
  transition: all 150ms ease;
}
.toolbar .actions button:hover { color: var(--ink); border-color: var(--accent-soft); }
.toolbar .actions button[aria-pressed="true"] {
  color: var(--accent);
  border-color: var(--accent);
}

main {
  max-width: 1024px;
  margin: 0 auto;
  padding: 28px 24px 80px;
}
@media (min-width: 800px) {
  main { padding: 40px 32px 120px; }
}

.paper {
  background: var(--paper);
  border-radius: 2px;
  box-shadow: var(--paper-shadow);
  padding: 56px 40px;
  position: relative;
}
@media (min-width: 800px) {
  .paper { padding: 80px 64px; }
}

.measure { max-width: 640px; margin-left: auto; margin-right: auto; }
.measure-wide { max-width: 720px; margin-left: auto; margin-right: auto; }

.meta {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
}
.meta-strong { color: var(--accent); }
.meta-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.meta-pct {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-faint);
  text-align: right;
  margin-top: 6px;
}
.sep { color: var(--ink-faint); margin: 0 8px; }

.spec-header { margin-bottom: 0; }
.spec-meta { margin-bottom: 12px; }
.spec-title {
  font-family: 'EB Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 38px;
  line-height: 1.15;
  letter-spacing: -0.012em;
  color: var(--ink);
  margin: 0;
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
  margin: 0 0 24px 0;
}

.stats {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 24px;
  margin-bottom: 24px;
}
.stat-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
  margin-bottom: 6px;
}
.stat-value {
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 32px;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  line-height: 1;
}
.stat-value .frac { color: var(--ink-faint); font-size: 24px; }
.stat-sub {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--ink-faint);
  margin-top: 6px;
}

.budget-meter { width: 100%; }
.bar-track {
  width: 100%; height: 3px; background: var(--hairline);
  overflow: hidden;
}
.bar-fill { height: 100%; transition: width 200ms ease; }
.bar-ok { background: var(--accent); }
.bar-warn { background: var(--warn); }
.bar-danger { background: var(--fail); }

.toc-block {
  border-top: 1px solid var(--hairline);
  border-bottom: 1px solid var(--hairline);
  padding: 24px 0;
  margin: 0 auto 56px;
  max-width: 720px;
}
.toc-list {
  list-style: none;
  padding: 0; margin: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
}
@media (max-width: 700px) { .toc-list { grid-template-columns: 1fr; } }
.toc-list li { line-height: 1.6; }
.toc-list li.hidden { display: none; }
.toc-list a {
  display: grid;
  grid-template-columns: 18px 48px 1fr;
  gap: 8px;
  padding: 4px 0;
  text-decoration: none;
  color: var(--ink);
  align-items: baseline;
  border-radius: 2px;
  transition: background 100ms ease;
}
.toc-list a:hover { background: var(--accent-faint); }
.toc-list .toc-glyph { color: var(--ink-faint); font-size: 10px; }
.toc-list li[data-status="done"] .toc-glyph { color: var(--pass); }
.toc-list li[data-status="in_progress"] .toc-glyph { color: var(--accent); }
.toc-list li[data-status="paused"] .toc-glyph { color: var(--warn); }
.toc-list .toc-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--ink-faint);
}
.toc-list .toc-title { color: var(--ink-muted); font-size: 14px; }
.toc-list .is-current a {
  background: var(--accent-faint);
}
.toc-list .is-current .toc-id,
.toc-list .is-current .toc-title { color: var(--accent); }

.intent-section {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 32px;
  margin-bottom: 48px;
  scroll-margin-top: 80px;
  transition: opacity 200ms ease;
}
.intent-section.hidden { display: none; }
.intent-section.dimmed { opacity: 0.35; }
.intent-num {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-faint);
  padding-top: 6px;
}
.intent-head {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  margin-bottom: 4px;
}
.intent-title {
  font-family: 'EB Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 19px;
  color: var(--ink);
  margin: 0;
}
.intent-meta { display: flex; align-items: center; gap: 0; flex-wrap: wrap; margin-bottom: 16px; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--ink-faint); }
.status { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em; }
.status-open { color: var(--ink-faint); }
.status-in_progress { color: var(--accent); }
.status-done { color: var(--pass); }
.status-paused { color: var(--warn); }

.checks { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--hairline); }
.check-item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--hairline);
}
.check-item:last-child { border-bottom: none; }
.check-glyph { font-size: 12px; padding-top: 4px; }
.glyph-pass { color: var(--pass); }
.glyph-fail { color: var(--fail); }
.glyph-pending { color: var(--ink-faint); }
.check-head { line-height: 1.55; }
.check-id {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  color: var(--ink-faint);
  margin-right: 8px;
}
.check-desc { color: var(--ink); }

.cmd-row {
  display: flex; align-items: stretch; gap: 6px;
  margin-top: 6px;
}
.cmd {
  flex: 1;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  background: var(--accent-faint);
  color: var(--ink-muted);
  padding: 6px 10px;
  border: 1px solid var(--hairline);
  word-break: break-all;
  white-space: pre-wrap;
}
.cmd-manual { color: var(--ink-faint); font-style: italic; background: transparent; }
.copy-btn {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  padding: 0 10px;
  background: transparent;
  border: 1px solid var(--hairline);
  color: var(--ink-faint);
  cursor: pointer;
  transition: all 100ms ease;
  white-space: nowrap;
}
.copy-btn:hover { color: var(--accent); border-color: var(--accent); }
.copy-id {
  align-self: baseline;
  padding: 4px 8px;
  font-size: 10.5px;
  letter-spacing: 0.14em;
}

details.audit-failure {
  margin-top: 16px;
  padding-left: 16px;
  border-left: 2px solid var(--fail);
}
details.audit-failure summary {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--fail);
  cursor: pointer;
  list-style: none;
  user-select: none;
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

footer.bottom {
  text-align: center;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
  margin-top: 32px;
}

#help-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: color-mix(in oklab, var(--bg) 80%, transparent);
  backdrop-filter: blur(4px);
  display: none;
  align-items: center; justify-content: center;
  padding: 32px;
}
#help-overlay[open] { display: flex; }
#help-overlay .panel {
  background: var(--paper);
  box-shadow: var(--paper-shadow);
  padding: 40px;
  max-width: 480px;
  width: 100%;
  border-radius: 2px;
}
#help-overlay h3 {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.16em;
  color: var(--ink-muted);
  margin: 0 0 24px 0;
}
#help-overlay dl { display: grid; grid-template-columns: auto 1fr; gap: 12px 24px; margin: 0; }
#help-overlay dt {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
}
#help-overlay dd { margin: 0; color: var(--ink); }

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

@media print {
  .toolbar, #help-overlay, #toasts, .copy-btn { display: none !important; }
  body { background: white; color: black; }
  .paper { box-shadow: none; padding: 0; }
  .intent-section { page-break-inside: avoid; opacity: 1 !important; }
  .intent-section.hidden { display: grid !important; }
  details { open: ""; }
  details summary { display: none; }
  details > *:not(summary) { display: block !important; }
}
"""


JS = """
(function() {
  const planId = document.documentElement.dataset.planId || 'default';
  const lsKey = 'gpr:viewer:' + planId;
  const state = Object.assign(
    { filter: 'all', search: '', theme: 'paper' },
    JSON.parse(localStorage.getItem(lsKey) || '{}')
  );

  function persist() { localStorage.setItem(lsKey, JSON.stringify(state)); }

  // --- theme ---
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    document.querySelectorAll('[data-theme-set]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.themeSet === t));
    });
  }
  document.querySelectorAll('[data-theme-set]').forEach(b => {
    b.addEventListener('click', () => {
      state.theme = b.dataset.themeSet;
      applyTheme(state.theme);
      persist();
    });
  });
  applyTheme(state.theme);

  // --- filter chips ---
  const sections = Array.from(document.querySelectorAll('.intent-section'));
  const tocItems = Array.from(document.querySelectorAll('.toc-list li[data-toc-id]'));
  function applyFilter() {
    const q = (state.search || '').trim().toLowerCase();
    const f = state.filter;
    sections.forEach(s => {
      const matchesStatus = f === 'all' || s.dataset.status === f;
      const matchesSearch = !q ||
        s.dataset.id.toLowerCase().includes(q) ||
        s.dataset.title.includes(q);
      s.classList.toggle('hidden', !(matchesStatus && matchesSearch));
    });
    tocItems.forEach(li => {
      const sec = document.getElementById('intent-' + li.dataset.tocId);
      li.classList.toggle('hidden', sec && sec.classList.contains('hidden'));
    });
    document.querySelectorAll('.chip').forEach(c => {
      c.setAttribute('aria-pressed', String(c.dataset.filter === f));
    });
  }
  document.querySelectorAll('.chip').forEach(c => {
    c.addEventListener('click', () => {
      state.filter = c.dataset.filter;
      applyFilter();
      persist();
    });
  });
  const searchInput = document.querySelector('.search');
  if (searchInput) {
    searchInput.value = state.search;
    searchInput.addEventListener('input', () => {
      state.search = searchInput.value;
      applyFilter();
      persist();
    });
  }
  applyFilter();

  // --- copy buttons ---
  document.querySelectorAll('[data-copy]').forEach(b => {
    b.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(b.dataset.copy);
        toast('copied');
      } catch (e) {
        toast('copy failed');
      }
    });
  });

  // --- toasts ---
  const toastBox = document.getElementById('toasts');
  function toast(msg) {
    if (!toastBox) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    toastBox.appendChild(el);
    setTimeout(() => el.remove(), 2000);
  }

  // --- keyboard navigation ---
  function visibleSections() {
    return sections.filter(s => !s.classList.contains('hidden'));
  }
  function currentIdx() {
    const visible = visibleSections();
    if (!visible.length) return -1;
    let best = 0, bestTop = -Infinity;
    visible.forEach((s, i) => {
      const top = s.getBoundingClientRect().top;
      if (top <= 96 && top > bestTop) { bestTop = top; best = i; }
    });
    return best;
  }
  function jumpTo(idx) {
    const v = visibleSections();
    if (!v.length) return;
    const target = v[Math.max(0, Math.min(v.length - 1, idx))];
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    history.replaceState(null, '', '#' + target.id);
  }
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      if (e.key === 'Escape') { e.target.blur(); }
      return;
    }
    const help = document.getElementById('help-overlay');
    if (e.key === '?') { e.preventDefault(); help.toggleAttribute('open'); }
    else if (e.key === 'Escape') { help.removeAttribute('open'); }
    else if (e.key === 'j') { e.preventDefault(); jumpTo(currentIdx() + 1); }
    else if (e.key === 'k') { e.preventDefault(); jumpTo(currentIdx() - 1); }
    else if (e.key === '/') { e.preventDefault(); searchInput && searchInput.focus(); }
  });

  // --- TOC current-section highlight ---
  if ('IntersectionObserver' in window) {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const id = en.target.dataset.id;
        tocItems.forEach(li => {
          li.classList.toggle('is-current', li.dataset.tocId === id);
        });
        const dagNode = document.querySelector('.mermaid svg [id^="flowchart-' + id + '-"]');
        if (dagNode) {
          document.querySelectorAll('.mermaid svg .is-current-node').forEach(n => n.classList.remove('is-current-node'));
          dagNode.classList.add('is-current-node');
        }
      });
    }, { rootMargin: '-30% 0px -60% 0px' });
    sections.forEach(s => obs.observe(s));
  }

  // --- close help on click-outside ---
  document.getElementById('help-overlay').addEventListener('click', (e) => {
    if (e.target.id === 'help-overlay') e.currentTarget.removeAttribute('open');
  });
})();
"""


HTML_SHELL = """\
<!doctype html>
<html lang="en" data-theme="paper" data-plan-id="{plan_id}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

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
<style>{css}</style>
</head>
<body>
<nav class="toolbar" role="toolbar">
  <div class="chips">
    <button class="chip" data-filter="all" aria-pressed="true">all</button>
    <button class="chip" data-filter="open" aria-pressed="false">open</button>
    <button class="chip" data-filter="in_progress" aria-pressed="false">in&nbsp;progress</button>
    <button class="chip" data-filter="done" aria-pressed="false">done</button>
    <button class="chip" data-filter="paused" aria-pressed="false">paused</button>
  </div>
  <input type="search" class="search" placeholder="filter intents · /">
  <div class="actions">
    <button data-theme-set="paper" aria-pressed="true">paper</button>
    <button data-theme-set="sepia" aria-pressed="false">sepia</button>
    <button data-theme-set="dark" aria-pressed="false">dark</button>
    <button id="help-btn" title="keyboard shortcuts (?)">?</button>
  </div>
</nav>

<main>
  <article class="paper">
{body}
  </article>
  <footer class="bottom">rendered by gpr render · press ? for shortcuts</footer>
</main>

<div id="help-overlay" role="dialog" aria-label="keyboard shortcuts">
  <div class="panel">
    <h3>keyboard shortcuts</h3>
    <dl>
      <dt>j</dt><dd>next visible intent</dd>
      <dt>k</dt><dd>previous visible intent</dd>
      <dt>/</dt><dd>focus filter / search</dd>
      <dt>?</dt><dd>toggle this overlay</dd>
      <dt>esc</dt><dd>close overlay or unfocus search</dd>
    </dl>
  </div>
</div>

<div id="toasts" aria-live="polite"></div>

<script>{js}</script>
<script>document.getElementById('help-btn').addEventListener('click', () => document.getElementById('help-overlay').toggleAttribute('open'));</script>
</body>
</html>
"""


def render(plan: dict[str, Any], state: dict[str, Any], gpr_dir: Path,
           project_root: Path) -> str:
    counts = _intent_counts(plan)
    total = sum(counts.values())
    done = counts.get("done", 0)
    pct = round((done / total) * 100, 1) if total else 0.0

    intents_html = "".join(
        _intent_section(i + 1, it) for i, it in enumerate(plan["intents"])
    )
    dag = _intent_dag_mermaid(plan)
    budget_html = _budget_meter(plan, state)
    events_html = _events_block(project_root)
    toc_html = _toc_block(plan)
    cost = state.get("costUsd", 0.0)
    tokens = state.get("tokensInput", 0) + state.get("tokensOutput", 0)
    wall = state.get("wallClockSeconds", 0.0)
    iteration = plan["globalState"]["iteration"]
    same_sig = plan["globalState"]["consecutiveSameSignature"]
    persona = plan.get("persona", {}).get("primary", "principal_engineer")

    body = f"""
    <header class="spec-header measure">
      <div class="meta spec-meta">
        <span>{_esc(plan["project"])}</span>
        <span class="sep">/</span>
        <span>branch · {_esc(plan["branch"])}</span>
        <span class="sep">/</span>
        <span class="meta-strong">{_esc(plan.get("status", "pursuing"))}</span>
        <span class="sep">/</span>
        <span>persona · {_esc(persona.replace("_", " "))}</span>
      </div>
      <h1 class="spec-title">{_esc(plan["goal"])}</h1>
    </header>

    <hr class="hairline">

    <section class="measure">
      <h2 class="section-h">progress</h2>
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
          {budget_html}
        </div>
      </div>
      <div class="meta" style="margin-top: 16px;">
        cost · ${_esc(round(cost, 2))}
        <span class="sep">·</span>
        tokens · {_esc(tokens)}
        <span class="sep">·</span>
        wall · {_esc(round(wall))}s
      </div>
    </section>

    <hr class="hairline">

    <section class="toc-block">
      <h2 class="section-h" style="text-align:center;">contents</h2>
      {toc_html}
    </section>

    <section class="measure-wide">
      <h2 class="section-h">intent graph</h2>
      <div style="overflow-x:auto; padding: 16px 0;">
        <pre class="mermaid">{_esc(dag)}</pre>
      </div>
    </section>

    <hr class="hairline">

    <section class="measure-wide">
      <h2 class="section-h">intents</h2>
      {intents_html}
    </section>

    <hr class="hairline">

    <section class="measure-wide">
      <h2 class="section-h">recent events</h2>
      {events_html}
    </section>
    """

    plan_id = (
        plan.get("project", "default") + "|"
        + (plan.get("createdAt", "") or "")
    )
    return HTML_SHELL.format(
        title=f"{_esc(plan['project'])} · gpr",
        plan_id=_esc(plan_id),
        css=CSS,
        js=JS,
        body=body,
    )
