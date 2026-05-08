"""Render the Plan as a self-contained HTML page.

Visual aesthetic borrows from making-software.com: a single white card
on a warm cream background, serif body at a generous measure with mono
metadata in small uppercase, a cobalt accent, paper-edge shadow, and
hairline rules. Cleanroom CSS — no copying from that site's
stylesheet. Tailwind via CDN, Mermaid via CDN, Google Fonts for the
serif (EB Garamond) and mono (JetBrains Mono).
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


def _status_label(status: str) -> str:
    palette = {
        "open": "text-stone-500",
        "in_progress": "text-cobalt-700",
        "done": "text-emerald-700",
        "paused": "text-amber-700",
    }
    cls = palette.get(status, "text-stone-500")
    return (
        f'<span class="font-mono text-[10px] uppercase tracking-[0.14em] {cls}">'
        f"{_esc(status.replace('_', ' '))}</span>"
    )


def _check_glyph(intent: dict[str, Any], check_id: str) -> str:
    proofs = {p.get("checkId"): p for p in intent.get("proofs", [])}
    if check_id in proofs:
        return '<span class="text-emerald-700" aria-label="proven">●</span>'
    failures = [
        f for f in intent.get("auditFailures", [])
        for d in f.get("audit", {}).get("details", [])
        if d.get("checkId") == check_id and d.get("result") == "fail"
    ]
    if failures:
        return '<span class="text-rose-700" aria-label="audit failed">●</span>'
    return '<span class="text-stone-300" aria-label="unchecked">○</span>'


def _intent_dag_mermaid(plan: dict[str, Any]) -> str:
    lines = ["graph LR"]
    for it in plan["intents"]:
        node_id = _esc(it["id"])
        title = _esc(it["title"])[:36]
        cls = {
            "open": "open",
            "in_progress": "wip",
            "done": "done",
            "paused": "paused",
        }.get(it["status"], "open")
        lines.append(f'    {node_id}["{node_id}<br/>{title}"]:::{cls}')
        for dep in it["dependsOn"]:
            lines.append(f"    {_esc(dep)} --> {node_id}")
    lines.append("    classDef open fill:#fafaf9,stroke:#d6d3d1,color:#44403c")
    lines.append("    classDef wip fill:#eff6ff,stroke:#1d4ed8,color:#1e3a8a")
    lines.append("    classDef done fill:#f0fdf4,stroke:#15803d,color:#14532d")
    lines.append("    classDef paused fill:#fffbeb,stroke:#b45309,color:#78350f")
    return "\n".join(lines)


def _budget_meter(plan: dict[str, Any], state: dict[str, Any]) -> str:
    bs = budget_mod.status(plan, state)
    f = bs["fraction_used"] or 0.0
    pct = round(f * 100, 1)
    if f >= 0.95:
        bar = "bg-rose-700"
    elif f >= 0.6:
        bar = "bg-amber-700"
    else:
        bar = "bg-cobalt-700"
    width = min(100, max(0, pct))
    axis = bs["binding_axis"] or "—"
    return (
        '<div class="w-full">'
        '<div class="flex items-baseline justify-between mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500">'
        f'<span>binding axis</span><span>{_esc(axis)}</span></div>'
        '<div class="w-full h-[3px] bg-stone-200 overflow-hidden">'
        f'<div class="h-full {bar}" style="width:{width}%"></div></div>'
        f'<div class="mt-1.5 font-mono text-[10px] tabular-nums text-stone-500 text-right">{pct}%</div>'
        '</div>'
    )


def _intent_section(idx: int, intent: dict[str, Any]) -> str:
    num = f"{idx:02d}"
    deps = ", ".join(_esc(d) for d in intent["dependsOn"]) or "—"
    checks_html = "".join(
        '<li class="grid grid-cols-[24px_60px_1fr] gap-x-3 items-baseline py-1.5 border-b border-stone-100 last:border-b-0">'
        f'<span class="text-base leading-none">{_check_glyph(intent, ch["id"])}</span>'
        f'<span class="font-mono text-[11px] tabular-nums text-stone-500">{_esc(ch["id"])}</span>'
        f'<span class="text-stone-800 leading-snug">{_esc(ch["description"])}'
        + (
            f'<div class="mt-1 font-mono text-[10.5px] text-stone-400 break-all">{_esc(ch.get("verifyCmd") or "(manual gate)")}</div>'
        )
        + '</span></li>'
        for ch in intent.get("checks", [])
    )
    fails = intent.get("auditFailures", [])
    fail_block = ""
    if fails:
        latest = fails[-1]
        fail_block = (
            '<aside class="mt-5 pl-4 border-l-2 border-rose-300/70">'
            '<div class="font-mono text-[10px] uppercase tracking-[0.14em] text-rose-700 mb-1">last audit failure</div>'
            f'<pre class="font-mono text-[11px] text-stone-600 whitespace-pre-wrap">{_esc(json.dumps(latest, indent=2)[:400])}</pre>'
            '</aside>'
        )
    return (
        f'<section class="grid grid-cols-[64px_1fr] gap-x-8 mb-12">'
        f'<div class="font-mono text-[11px] tabular-nums text-stone-400 pt-1.5">{num}</div>'
        '<div>'
        f'<div class="flex items-baseline gap-3 mb-1">'
        f'<h3 class="text-lg font-medium text-stone-900 leading-tight">{_esc(intent["title"])}</h3>'
        f'</div>'
        f'<div class="flex items-center gap-3 mb-4">'
        f'<span class="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-400">{_esc(intent["id"])}</span>'
        f'<span class="text-stone-300">·</span>'
        f'{_status_label(intent["status"])}'
        f'<span class="text-stone-300">·</span>'
        f'<span class="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-400">'
        f'priority {_esc(intent["priority"])}</span>'
        f'<span class="text-stone-300">·</span>'
        f'<span class="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-400">'
        f'depends · {_esc(deps)}</span>'
        f'</div>'
        f'<ul class="border-t border-stone-100">{checks_html}</ul>'
        f'{fail_block}'
        f'</div>'
        '</section>'
    )


def _events_block(project_root: Path, n: int = 24) -> str:
    events = events_mod.tail(project_root, n=n)
    if not events:
        return '<p class="text-stone-400 italic">no events yet</p>'
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
        else:
            detail = ""
        rows.append(
            '<tr class="border-b border-stone-100 last:border-b-0">'
            f'<td class="py-2 pr-4 font-mono text-[10.5px] text-stone-400 align-top w-20 tabular-nums">{time_str}</td>'
            f'<td class="py-2 pr-4 font-mono text-[10.5px] uppercase tracking-[0.14em] text-stone-700 align-top w-40">{kind}</td>'
            f'<td class="py-2 font-mono text-[11px] text-stone-500 align-top">{detail}</td>'
            '</tr>'
        )
    return f'<table class="w-full text-left">{"".join(rows)}</table>'


HTML_SHELL = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {{
  theme: {{
    extend: {{
      fontFamily: {{
        serif: ['"EB Garamond"', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      }},
      colors: {{
        cream: '#fbfaf6',
        ink: '#171717',
        cobalt: {{
          50: '#f5f7fb',
          100: '#dfe4f1',
          200: '#bccae3',
          300: '#8fa4d2',
          400: '#6582bd',
          500: '#4262a8',
          600: '#2c4a90',
          700: '#1f3873',
          800: '#162a57',
          900: '#0e1d3e',
        }},
      }},
      letterSpacing: {{ widest2: '0.16em' }},
    }}
  }}
}}
</script>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{
  startOnLoad: true,
  theme: 'neutral',
  securityLevel: 'loose',
  themeVariables: {{
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: '12px',
    primaryColor: '#fff',
    primaryBorderColor: '#1f3873',
    primaryTextColor: '#1c1917',
    lineColor: '#a8a29e',
  }}
}});
</script>

<style>
  html, body {{
    background: #fbfaf6;
    color: #171717;
    font-family: 'EB Garamond', serif;
    font-feature-settings: 'liga', 'calt';
  }}
  .paper {{
    background: #ffffff;
    border-radius: 2px;
    box-shadow:
      0 1px 4px 1px rgba(0,0,0,0.05),
      0 1px 1px 0 rgba(0,0,0,0.06),
      0 -1px 1px 1px #ffffff inset;
  }}
  .prose-body {{
    font-family: 'EB Garamond', serif;
    font-size: 17px;
    line-height: 1.62;
    color: #1c1917;
  }}
  .prose-body p {{ margin: 0 0 1em 0; }}
  .prose-body p.lede::first-letter {{
    initial-letter: 2 1;
    -webkit-initial-letter: 2 1;
    font-weight: 600;
    padding-right: 8px;
    color: #1f3873;
  }}
  .meta {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: #78716c;
  }}
  .meta-strong {{
    color: #1f3873;
  }}
  .display-h1 {{
    font-family: 'EB Garamond', serif;
    font-weight: 500;
    font-size: 38px;
    line-height: 1.15;
    letter-spacing: -0.012em;
    color: #1c1917;
  }}
  .display-h2 {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    font-weight: 600;
    color: #44403c;
  }}
  hr.hairline {{
    border: none;
    border-top: 1px solid #eae7e1;
    margin: 56px 0;
  }}
  .mermaid {{ background: transparent; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .tabular-figs {{ font-variant-numeric: tabular-nums; }}
</style>
</head>
<body class="antialiased">
<main class="max-w-5xl mx-auto px-4 sm:px-8 py-12">
  <article class="paper px-8 sm:px-16 py-14 sm:py-20">
{body}
  </article>
  <footer class="mt-8 text-center meta">
    rendered by <span class="meta-strong">gpr render</span>
  </footer>
</main>
</body>
</html>
"""


def _intent_counts(plan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in plan["intents"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return counts


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
    cost = state.get("costUsd", 0.0)
    tokens = state.get("tokensInput", 0) + state.get("tokensOutput", 0)
    wall = state.get("wallClockSeconds", 0.0)
    iteration = plan["globalState"]["iteration"]
    same_sig = plan["globalState"]["consecutiveSameSignature"]

    body = f"""
    <header class="mx-auto" style="max-width: 640px;">
      <div class="meta mb-3">
        <span>{_esc(plan["project"])}</span>
        <span class="text-stone-300 mx-2">/</span>
        <span>branch · {_esc(plan["branch"])}</span>
        <span class="text-stone-300 mx-2">/</span>
        <span class="meta-strong">{_esc(plan.get("status", "pursuing"))}</span>
      </div>
      <h1 class="display-h1 mb-6">{_esc(plan["goal"])}</h1>
    </header>

    <hr class="hairline">

    <section class="mx-auto" style="max-width: 640px;">
      <h2 class="display-h2 mb-6">progress</h2>
      <dl class="grid grid-cols-3 gap-x-6 gap-y-1 mb-6">
        <div>
          <dt class="meta mb-1">intents</dt>
          <dd class="font-serif text-3xl tabular-figs text-stone-900">{done}<span class="text-stone-400 text-2xl"> / {total}</span></dd>
          <dd class="meta mt-1">{pct}% done</dd>
        </div>
        <div>
          <dt class="meta mb-1">iteration</dt>
          <dd class="font-serif text-3xl tabular-figs text-stone-900">{iteration}</dd>
          <dd class="meta mt-1">same-sig {same_sig}</dd>
        </div>
        <div>
          <dt class="meta mb-1">budget</dt>
          <dd>{budget_html}</dd>
        </div>
      </dl>
      <div class="meta tabular-figs">
        cost · ${_esc(round(cost, 2))}
        <span class="text-stone-300 mx-2">·</span>
        tokens · {_esc(tokens):>0}
        <span class="text-stone-300 mx-2">·</span>
        wall · {_esc(round(wall))}s
      </div>
    </section>

    <hr class="hairline">

    <section class="mx-auto" style="max-width: 720px;">
      <h2 class="display-h2 mb-6">intent graph</h2>
      <div class="overflow-x-auto py-4">
        <pre class="mermaid">{_esc(dag)}</pre>
      </div>
    </section>

    <hr class="hairline">

    <section class="mx-auto" style="max-width: 720px;">
      <h2 class="display-h2 mb-8">intents</h2>
      {intents_html}
    </section>

    <hr class="hairline">

    <section class="mx-auto" style="max-width: 720px;">
      <h2 class="display-h2 mb-6">recent events</h2>
      {events_html}
    </section>
    """

    return HTML_SHELL.format(
        title=f"{_esc(plan['project'])} · gpr",
        body=body,
    )
