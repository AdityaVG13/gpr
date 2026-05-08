"""Render the Plan as a self-contained HTML page.

Output is a single .gpr/Plan.html with Tailwind via CDN, Mermaid for
the intent DAG, no JS framework, no build step. Refresh by re-running
`gpr render`.
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


def _status_badge(status: str) -> str:
    palette = {
        "open": ("bg-zinc-800", "text-zinc-200"),
        "in_progress": ("bg-blue-900/60", "text-blue-200"),
        "done": ("bg-emerald-900/60", "text-emerald-200"),
        "paused": ("bg-amber-900/60", "text-amber-200"),
    }
    bg, fg = palette.get(status, ("bg-zinc-800", "text-zinc-200"))
    return (
        f'<span class="rounded-full px-2 py-0.5 text-xs font-medium {bg} {fg}">'
        f"{_esc(status)}</span>"
    )


def _check_glyph(intent: dict[str, Any], check_id: str) -> str:
    proofs = {p.get("checkId"): p for p in intent.get("proofs", [])}
    if check_id in proofs:
        return '<span class="text-emerald-400">●</span>'
    failures = [
        f for f in intent.get("auditFailures", [])
        for d in f.get("audit", {}).get("details", [])
        if d.get("checkId") == check_id and d.get("result") == "fail"
    ]
    if failures:
        return '<span class="text-red-400">●</span>'
    return '<span class="text-zinc-500">○</span>'


def _intent_dag_mermaid(plan: dict[str, Any]) -> str:
    """Build a Mermaid `graph TD` source for the intent DAG."""
    lines = ["graph LR"]
    for it in plan["intents"]:
        node_id = _esc(it["id"])
        label = f"{node_id}<br/>{_esc(it['title'])[:40]}"
        cls = {
            "open": "open",
            "in_progress": "wip",
            "done": "done",
            "paused": "paused",
        }.get(it["status"], "open")
        lines.append(f'    {node_id}["{label}"]:::{cls}')
        for dep in it["dependsOn"]:
            lines.append(f"    {_esc(dep)} --> {node_id}")
    lines.append("    classDef open fill:#1f2937,stroke:#52525b,color:#e4e4e7")
    lines.append("    classDef wip fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe")
    lines.append("    classDef done fill:#064e3b,stroke:#10b981,color:#a7f3d0")
    lines.append("    classDef paused fill:#78350f,stroke:#f59e0b,color:#fde68a")
    return "\n".join(lines)


def _budget_bar(plan: dict[str, Any], state: dict[str, Any]) -> str:
    bs = budget_mod.status(plan, state)
    f = bs["fraction_used"] or 0.0
    pct = round(f * 100, 1)
    if f >= 0.95:
        color = "bg-red-500"
    elif f >= 0.6:
        color = "bg-amber-500"
    else:
        color = "bg-emerald-500"
    width = min(100, max(0, pct))
    axis = bs["binding_axis"] or "—"
    return (
        f'<div class="w-full">'
        f'<div class="flex justify-between text-xs text-zinc-400 mb-1">'
        f'<span>binding axis: {_esc(axis)}</span>'
        f'<span>{pct}%</span></div>'
        f'<div class="w-full h-2 bg-zinc-800 rounded-full overflow-hidden">'
        f'<div class="h-full {color}" style="width:{width}%"></div></div></div>'
    )


def _intent_card(intent: dict[str, Any]) -> str:
    deps = ", ".join(_esc(d) for d in intent["dependsOn"]) or "—"
    checks_html = "".join(
        f'<li class="flex gap-2 items-start text-sm">'
        f'<span class="mt-0.5">{_check_glyph(intent, ch["id"])}</span>'
        f'<span class="text-zinc-200 font-mono text-xs">{_esc(ch["id"])}</span>'
        f'<span class="text-zinc-300">{_esc(ch["description"])}</span>'
        f'</li>'
        for ch in intent.get("checks", [])
    )
    fails = intent.get("auditFailures", [])
    fails_html = ""
    if fails:
        latest = fails[-1]
        fails_html = (
            '<div class="mt-3 rounded border border-red-900/40 bg-red-950/30 p-3">'
            '<div class="text-xs text-red-300 font-medium mb-1">last audit failure</div>'
            f'<div class="text-xs text-zinc-300 font-mono whitespace-pre-wrap">'
            f'{_esc(json.dumps(latest, indent=2)[:400])}</div></div>'
        )
    return (
        '<div class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">'
        f'<div class="flex items-center justify-between mb-2">'
        f'<div class="flex items-center gap-3">'
        f'<span class="font-mono text-sm text-zinc-400">{_esc(intent["id"])}</span>'
        f'<span class="font-medium text-zinc-100">{_esc(intent["title"])}</span>'
        f'</div>'
        f'{_status_badge(intent["status"])}'
        f'</div>'
        f'<div class="text-xs text-zinc-500 mb-3">priority {_esc(intent["priority"])} · '
        f'depends on {_esc(deps)}</div>'
        f'<ul class="space-y-1.5">{checks_html}</ul>'
        f'{fails_html}'
        '</div>'
    )


def _intent_counts(plan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in plan["intents"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return counts


def _events_block(project_root: Path, n: int = 30) -> str:
    events = events_mod.tail(project_root, n=n)
    if not events:
        return '<div class="text-sm text-zinc-500">no events yet</div>'
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
                detail += f" audit={audit.get('pass', 0)}/{audit.get('pass', 0)+audit.get('fail', 0)+audit.get('manual', 0)}"
        elif kind == "layer2_audit":
            v = e.get("verdict", {})
            detail = f"intent={_esc(e.get('intent'))} verdict={_esc(v.get('verdict'))}"
        elif kind == "reverse_audit":
            detail = f"clean={_esc(e.get('clean'))} rec={_esc(e.get('recommendation'))}"
        else:
            detail = ""
        rows.append(
            f'<tr class="border-b border-zinc-900">'
            f'<td class="py-1.5 pr-3 text-zinc-500 font-mono text-xs">{time_str}</td>'
            f'<td class="py-1.5 pr-3 text-zinc-300 text-xs font-medium">{kind}</td>'
            f'<td class="py-1.5 text-zinc-400 text-xs font-mono">{detail}</td>'
            f'</tr>'
        )
    return f'<table class="w-full text-left">{"".join(rows)}</table>'


HTML_SHELL = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{startOnLoad:true,theme:'dark',securityLevel:'loose'}});
</script>
<style>
  body{{font-feature-settings:"ss01","cv11";}}
  .mermaid svg{{max-width:100%;height:auto;}}
</style>
</head>
<body class="bg-zinc-950 text-zinc-100 antialiased">
<div class="max-w-6xl mx-auto px-6 py-10">
{body}
</div>
</body>
</html>
"""


def render(plan: dict[str, Any], state: dict[str, Any], gpr_dir: Path,
           project_root: Path) -> str:
    counts = _intent_counts(plan)
    total = sum(counts.values())
    done = counts.get("done", 0)
    pct = round((done / total) * 100, 1) if total else 0.0

    intents_html = "".join(_intent_card(it) for it in plan["intents"])
    dag = _intent_dag_mermaid(plan)
    budget_html = _budget_bar(plan, state)
    events_html = _events_block(project_root)

    body = (
        f'<header class="mb-8">'
        f'<div class="flex items-baseline gap-3 mb-1">'
        f'<h1 class="text-2xl font-bold tracking-tight">{_esc(plan["project"])}</h1>'
        f'<span class="text-zinc-500 text-sm font-mono">branch {_esc(plan["branch"])}</span>'
        f'<span class="text-zinc-500 text-sm">·</span>'
        f'<span class="text-zinc-400 text-sm">{_esc(plan.get("status", "pursuing"))}</span>'
        f'</div>'
        f'<p class="text-zinc-300 text-base max-w-3xl">{_esc(plan["goal"])}</p>'
        f'</header>'

        f'<section class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">'
        f'<div class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">'
        f'<div class="text-xs text-zinc-500 mb-1">progress</div>'
        f'<div class="text-2xl font-bold tabular-nums">{done} / {total}</div>'
        f'<div class="text-xs text-zinc-400">{pct}% intents done</div>'
        f'</div>'
        f'<div class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">'
        f'<div class="text-xs text-zinc-500 mb-1">iteration</div>'
        f'<div class="text-2xl font-bold tabular-nums">'
        f'{_esc(plan["globalState"]["iteration"])}</div>'
        f'<div class="text-xs text-zinc-400">consecutive same-sig: '
        f'{_esc(plan["globalState"]["consecutiveSameSignature"])}</div>'
        f'</div>'
        f'<div class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">'
        f'<div class="text-xs text-zinc-500 mb-2">budget</div>'
        f'{budget_html}'
        f'<div class="text-xs text-zinc-400 mt-2">'
        f'${_esc(round(state.get("costUsd", 0.0), 2))} · '
        f'{_esc(state.get("tokensInput", 0) + state.get("tokensOutput", 0))} tokens · '
        f'{_esc(round(state.get("wallClockSeconds", 0.0)))}s'
        f'</div>'
        f'</div>'
        f'</section>'

        f'<section class="mb-10">'
        f'<h2 class="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-3">intent graph</h2>'
        f'<div class="rounded-lg border border-zinc-800 bg-zinc-900/30 p-6 overflow-x-auto">'
        f'<pre class="mermaid">{_esc(dag)}</pre>'
        f'</div>'
        f'</section>'

        f'<section class="mb-10">'
        f'<h2 class="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-3">intents</h2>'
        f'<div class="space-y-3">{intents_html}</div>'
        f'</section>'

        f'<section class="mb-10">'
        f'<h2 class="text-sm font-semibold uppercase tracking-wider text-zinc-500 mb-3">recent events</h2>'
        f'<div class="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">'
        f'{events_html}'
        f'</div>'
        f'</section>'

        f'<footer class="text-xs text-zinc-600 mt-12 pt-6 border-t border-zinc-900">'
        f'rendered by <span class="font-mono text-zinc-500">gpr render</span> · '
        f'refresh by re-running the command'
        f'</footer>'
    )

    return HTML_SHELL.format(
        title=f"gpr · {_esc(plan['project'])}",
        body=body,
    )
