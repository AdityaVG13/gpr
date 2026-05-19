# shellcheck shell=bash
# Adapter-driven agent dispatcher. No hardcoded allow-list — any CLI on
# PATH can drive the loop. Adapter JSON describes how to invoke the
# binary, where to put the prompt, which flag carries the model id, and
# which stream-usage parser to apply.
#
# Resolution order for the adapter named <agent>:
#   1. .gpr/agents/<agent>.json                (project override)
#   2. ~/.config/gpr/agents/<agent>.json       (user)
#   3. $GPR_LIB/agents/builtin/<agent>.json    (shipped: claude, codex,
#                                                opencode, gemini, echo)
#   4. synthesised generic stdin-passthrough adapter if `command -v
#      <agent>` resolves — i.e. ANY CLI on PATH just works.
#
# Compatible with bash 3.2 (macOS bundled). No associative arrays.
#
# Adapter schema (JSON):
#   {
#     "name": "...",
#     "cmd": "binary-on-path",
#     "args": ["--flag", "value"],
#     "prompt": "stdin" | "argv_last" | "argv_named",
#     "prompt_flag": "--prompt"      # only when prompt = argv_named
#     "model_flag": "--model" | null,  # forward GPR_MODEL when set
#     "model_id_default": "...",     # cost-accounting fallback
#     "stream_format": "passthrough" | "claude_stream_json" | "codex_json",
#     "non_interactive_flags": [],
#     "timeout_seconds": 1800
#   }
#
# One-shot custom adapter via env:
#   GPR_AGENT_CUSTOM_CMD="ollama run llama3"
#   GPR_AGENT_CUSTOM_PROMPT_MODE="stdin"      # or argv_last / argv_named
#   GPR_AGENT_CUSTOM_PROMPT_FLAG="--prompt"   # only for argv_named
#   gpr run --agent custom
#
# Extra args: callers can append flags via GPR_AGENT_EXTRA_ARGS. The
# value is split with `eval` on a single line, so quoting follows shell
# rules.

GPR_LIB="${GPR_LIB:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# --- public surface -----------------------------------------------------------

# Always returns 0: we accept any agent name. Resolution failure surfaces
# at agent_run time with a clear error.
agent_supports() {
  return 0
}

# Best-effort model id for cost accounting. Order:
#   1. $GPR_MODEL if set
#   2. adapter.model_id_default
#   3. "default"
agent_model_id() {
  if [[ -n "${GPR_MODEL:-}" ]]; then
    printf '%s' "$GPR_MODEL"
    return
  fi
  local adapter
  if ! adapter=$(_agent_resolve_adapter "$1"); then
    printf 'default'
    return
  fi
  local m
  m=$(printf '%s' "$adapter" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('model_id_default') or 'default')
except Exception:
    print('default')
")
  printf '%s' "$m"
}

# Stream-format for token-usage parsing. Read by loop.sh via the python
# `lib.state.budget.parse_usage(stream_format, lines)` path. We map the
# adapter's stream_format onto the registered parsers.
agent_stream_format() {
  local adapter
  if ! adapter=$(_agent_resolve_adapter "$1"); then
    printf 'passthrough'
    return
  fi
  printf '%s' "$adapter" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('stream_format', 'passthrough'))
except Exception:
    print('passthrough')
"
}

# Dispatch by name. The echo agent is synthesised locally and bypasses
# any binary lookup; every other name routes through the generic
# adapter-driven invocation path.
agent_run() {
  local agent="$1" stream_log="$2" timeout_sec="${3:-}"
  if [[ "$agent" == "echo" ]]; then
    _agent_run_echo "$stream_log"
    return $?
  fi
  local adapter
  if ! adapter=$(_agent_resolve_adapter "$agent"); then
    printf 'gpr: no adapter for %s and no such binary on PATH\n' "$agent" >&2
    return 127
  fi
  _agent_run_generic "$agent" "$adapter" "$stream_log" "$timeout_sec"
}

# --- internals ----------------------------------------------------------------

# Print the adapter JSON for <name>. Sources, in order: project, user,
# built-in, one-shot env, synthetic-passthrough. Returns 1 only when
# every path failed.
_agent_resolve_adapter() {
  local name="$1"
  local proj_dir="${GPR_PROJECT_ROOT:-$PWD}/.gpr/agents"
  local user_dir="${XDG_CONFIG_HOME:-$HOME/.config}/gpr/agents"
  local builtin_dir="$GPR_LIB/agents/builtin"
  for candidate in \
    "$proj_dir/$name.json" \
    "$user_dir/$name.json" \
    "$builtin_dir/$name.json"; do
    if [[ -f "$candidate" ]]; then
      cat "$candidate"
      return 0
    fi
  done
  # One-shot custom adapter via env (use --agent custom + GPR_AGENT_CUSTOM_CMD).
  if [[ "$name" == "custom" && -n "${GPR_AGENT_CUSTOM_CMD:-}" ]]; then
    _agent_custom_from_env
    return 0
  fi
  # Synthesise a generic stdin-passthrough adapter if the binary exists.
  if command -v "$name" >/dev/null 2>&1; then
    _agent_synthetic_passthrough "$name"
    return 0
  fi
  return 1
}

# Build a synthetic adapter that just execs <name> and feeds the prompt
# on stdin. Works for any CLI that accepts a prompt that way (most LLM
# tools, e.g. `llm`, `ollama run`, `grok chat`).
_agent_synthetic_passthrough() {
  local name="$1"
  cat <<JSON
{
  "name": "$name",
  "cmd": "$name",
  "args": [],
  "prompt": "stdin",
  "prompt_flag": null,
  "model_flag": null,
  "model_id_default": null,
  "stream_format": "passthrough",
  "non_interactive_flags": [],
  "timeout_seconds": 1800
}
JSON
}

# Build an adapter from one-shot env vars. Splits GPR_AGENT_CUSTOM_CMD on
# whitespace; the first token is the binary, the rest are args.
_agent_custom_from_env() {
  local cmd_full="${GPR_AGENT_CUSTOM_CMD}"
  local prompt_mode="${GPR_AGENT_CUSTOM_PROMPT_MODE:-stdin}"
  local prompt_flag="${GPR_AGENT_CUSTOM_PROMPT_FLAG:-}"
  python3 - "$cmd_full" "$prompt_mode" "$prompt_flag" <<'PY'
import json, shlex, sys
parts = shlex.split(sys.argv[1])
binary = parts[0] if parts else ""
extra = parts[1:]
mode = sys.argv[2] or "stdin"
pf = sys.argv[3] or None
print(json.dumps({
    "name": "custom",
    "cmd": binary,
    "args": extra,
    "prompt": mode,
    "prompt_flag": pf,
    "model_flag": None,
    "model_id_default": None,
    "stream_format": "passthrough",
    "non_interactive_flags": [],
    "timeout_seconds": 1800,
}))
PY
}

# Resolve a timeout-runner. Linux ships GNU coreutils (`timeout`),
# Homebrew on macOS provides `gtimeout`. If neither is available the
# wrapper degrades to a no-op so the agent still runs.
_agent_resolve_timeout() {
  local secs="$1"
  [[ -z "$secs" || "$secs" -eq 0 ]] && { printf ''; return; }
  if command -v timeout >/dev/null 2>&1; then
    printf 'timeout %s' "$secs"
  elif command -v gtimeout >/dev/null 2>&1; then
    printf 'gtimeout %s' "$secs"
  else
    printf ''
  fi
}

# Build the argv from an adapter, handling prompt-mode and model-flag.
# Output: one argv element per line. Caller reads into an array, then
# (for stdin mode) pipes the prompt; for argv_last/argv_named modes the
# prompt is appended as the LAST arg (argv_last) or after prompt_flag
# (argv_named).
_agent_build_argv() {
  local adapter_json="$1" prompt="$2"
  printf '%s' "$adapter_json" | python3 - "$prompt" <<'PY'
import json, os, shlex, sys
adapter = json.load(sys.stdin)
prompt = sys.argv[1] if len(sys.argv) > 1 else ""
argv = [adapter["cmd"]]
argv.extend(adapter.get("args") or [])
argv.extend(adapter.get("non_interactive_flags") or [])
# Forward --model when GPR_MODEL is set and the adapter declares a flag.
mflag = adapter.get("model_flag")
mid = os.environ.get("GPR_MODEL")
if mflag and mid:
    argv.extend([mflag, mid])
# Extra user-supplied flags via GPR_AGENT_EXTRA_ARGS (shell-quoted).
extra = os.environ.get("GPR_AGENT_EXTRA_ARGS", "").strip()
if extra:
    argv.extend(shlex.split(extra))
mode = adapter.get("prompt", "stdin")
if mode == "argv_last":
    argv.append(prompt)
elif mode == "argv_named":
    pflag = adapter.get("prompt_flag") or "--prompt"
    argv.extend([pflag, prompt])
# stdin mode: prompt is NOT in argv; caller pipes it on stdin.
for tok in argv:
    print(tok)
PY
}

# Generic adapter-driven invocation. Reads the prompt on stdin, builds
# argv per adapter, runs under `timeout`, tees stream output. Prints raw
# stdout to its caller (loop.sh captures it via process substitution).
_agent_run_generic() {
  local agent="$1" adapter_json="$2" stream_log="$3" timeout_sec="$4"
  local binary
  binary=$(printf '%s' "$adapter_json" | python3 -c "
import json, sys
print(json.load(sys.stdin)['cmd'])
")
  if ! command -v "$binary" >/dev/null 2>&1; then
    printf 'gpr: %s CLI not found on PATH (required by adapter %s)\n' \
      "$binary" "$agent" >&2
    return 127
  fi
  local prompt
  prompt="$(cat)"
  local mode
  mode=$(printf '%s' "$adapter_json" | python3 -c "
import json, sys
print(json.load(sys.stdin).get('prompt', 'stdin'))
")
  local argv=()
  while IFS= read -r line; do
    argv+=("$line")
  done < <(_agent_build_argv "$adapter_json" "$prompt")
  local timeout_argv
  if [[ -z "$timeout_sec" ]]; then
    timeout_sec=$(printf '%s' "$adapter_json" | python3 -c "
import json, sys
print(json.load(sys.stdin).get('timeout_seconds', 1800))
")
  fi
  timeout_argv=$(_agent_resolve_timeout "$timeout_sec")
  local raw
  if [[ "$mode" == "stdin" ]]; then
    if [[ -n "$timeout_argv" ]]; then
      # shellcheck disable=SC2086
      raw="$(printf '%s' "$prompt" | $timeout_argv "${argv[@]}" 2>&1 | tee "$stream_log")"
    else
      raw="$(printf '%s' "$prompt" | "${argv[@]}" 2>&1 | tee "$stream_log")"
    fi
  else
    if [[ -n "$timeout_argv" ]]; then
      # shellcheck disable=SC2086
      raw="$($timeout_argv "${argv[@]}" 2>&1 | tee "$stream_log")"
    else
      raw="$("${argv[@]}" 2>&1 | tee "$stream_log")"
    fi
  fi
  printf '%s' "$raw"
}

# echo agent: reads prompt, synthesises a fake signal block, writes to
# stream log + stdout. Used by tests/e2e_dryrun.sh and gpr doctor.
_agent_run_echo() {
  local stream_log="$1"
  local prompt
  prompt="$(cat)"
  local intent
  intent="$(printf '%s' "$prompt" | grep -E '^Intent: ' | head -n1 | awk '{print $2}')"
  intent="${intent:-UNKNOWN}"
  local out
  out=$(cat <<EOF
[echo agent — dry run]
Read prompt for intent ${intent}.

---gpr-signal---
{"status":"progress","intent":"${intent}","checks_attempted":[],"memory":{"mode":"append","content":"echo dry run iteration"}}
---end---
EOF
)
  printf '%s' "$out" | tee "$stream_log"
}
