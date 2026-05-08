# shellcheck shell=bash
# Per-agent CLI invocation. Each agent function:
#   - takes the rendered prompt on stdin
#   - prints raw stdout (so callers can grep for the signal block)
#   - writes a stream log to $1 (path)
#   - writes the model id to $2 (path) on the second line of stream log

agent_supports() {
  local agent="$1"
  case "$agent" in
    claude|codex|opencode|gemini|echo) return 0 ;;
    *) return 1 ;;
  esac
}

# Invoke claude in print + stream-json mode. Surface raw stdout to caller.
agent_claude() {
  local stream_log="$1" timeout_sec="${2:-1800}"
  if ! command -v claude >/dev/null 2>&1; then
    log_fail "claude CLI not found on PATH"
    return 127
  fi
  local prompt
  prompt="$(cat)"
  local raw
  raw="$(GPR_TIMEOUT=$timeout_sec /usr/bin/env bash -c '
    timeout "$GPR_TIMEOUT" claude \
      --print \
      --output-format stream-json \
      --verbose \
      --dangerously-skip-permissions \
      --append-system-prompt "$0" 2>&1 | tee "$1"
  ' "$prompt" "$stream_log")"
  printf '%s' "$raw"
}

# codex: --json output, exec mode (non-interactive).
agent_codex() {
  local stream_log="$1" timeout_sec="${2:-1800}"
  if ! command -v codex >/dev/null 2>&1; then
    log_fail "codex CLI not found on PATH"
    return 127
  fi
  local prompt
  prompt="$(cat)"
  local raw
  raw="$(GPR_TIMEOUT=$timeout_sec /usr/bin/env bash -c '
    timeout "$GPR_TIMEOUT" codex exec \
      --dangerously-bypass-approvals-and-sandbox \
      --json \
      "$0" 2>&1 | tee "$1"
  ' "$prompt" "$stream_log")"
  printf '%s' "$raw"
}

# opencode: --no-confirm one-shot run.
agent_opencode() {
  local stream_log="$1" timeout_sec="${2:-1800}"
  if ! command -v opencode >/dev/null 2>&1; then
    log_fail "opencode CLI not found on PATH"
    return 127
  fi
  local prompt
  prompt="$(cat)"
  local raw
  raw="$(GPR_TIMEOUT=$timeout_sec /usr/bin/env bash -c '
    timeout "$GPR_TIMEOUT" opencode run --no-confirm "$0" 2>&1 | tee "$1"
  ' "$prompt" "$stream_log")"
  printf '%s' "$raw"
}

# gemini-cli (community). Best-effort.
agent_gemini() {
  local stream_log="$1" timeout_sec="${2:-1800}"
  if ! command -v gemini >/dev/null 2>&1; then
    log_fail "gemini CLI not found on PATH"
    return 127
  fi
  local prompt
  prompt="$(cat)"
  local raw
  raw="$(GPR_TIMEOUT=$timeout_sec /usr/bin/env bash -c '
    timeout "$GPR_TIMEOUT" gemini --yolo --prompt "$0" 2>&1 | tee "$1"
  ' "$prompt" "$stream_log")"
  printf '%s' "$raw"
}

# echo: dry-run / smoke-test agent. Reads prompt and emits a fake signal.
# Used by tests/e2e_dryrun.sh and the doctor command.
agent_echo() {
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

# Dispatch by name.
agent_run() {
  local agent="$1" stream_log="$2" timeout_sec="${3:-1800}"
  case "$agent" in
    claude)   agent_claude   "$stream_log" "$timeout_sec" ;;
    codex)    agent_codex    "$stream_log" "$timeout_sec" ;;
    opencode) agent_opencode "$stream_log" "$timeout_sec" ;;
    gemini)   agent_gemini   "$stream_log" "$timeout_sec" ;;
    echo)     agent_echo     "$stream_log" ;;
    *) log_fail "unknown agent: $agent"; return 2 ;;
  esac
}

# Best-effort model id for cost accounting. Override via GPR_MODEL.
agent_model_id() {
  local agent="$1"
  if [[ -n "${GPR_MODEL:-}" ]]; then
    printf '%s' "$GPR_MODEL"
    return
  fi
  case "$agent" in
    claude)   printf 'claude-opus-4-7' ;;
    codex)    printf 'gpt-5-codex' ;;
    opencode) printf 'default' ;;
    gemini)   printf 'default' ;;
    echo)     printf 'default' ;;
    *)        printf 'default' ;;
  esac
}
