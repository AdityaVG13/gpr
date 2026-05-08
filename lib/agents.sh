# shellcheck shell=bash
# Per-agent CLI invocation. The dispatcher path is one generic function
# (_agent_run_generic) plus a single case statement that yields each
# agent's argv (binary + flags). Adding a new agent = one case branch.
#
# Compatible with bash 3.2 (macOS bundled). No associative arrays.
#
# Invariant: every supported coding-agent CLI we wrap accepts its
# prompt as the LAST positional argument (after all flags).
#
# Extra args: callers can append flags via GPR_AGENT_EXTRA_ARGS. The
# value is split with `eval` on a single line, so quoting follows shell
# rules. Use this to opt the user's MCP servers, allowed-tools list,
# hooks-config, model override, etc. into the agent invocation.
# Example:
#   GPR_AGENT_EXTRA_ARGS='--mcp-config ~/.claude/mcp.json --allowedTools "Bash(rtk *)"' \
#     gpr run --agent claude

# --- public surface -----------------------------------------------------------

agent_supports() {
  case "$1" in
    claude|codex|opencode|gemini|echo) return 0 ;;
    *) return 1 ;;
  esac
}

# Best-effort model id for cost accounting. Override via GPR_MODEL.
agent_model_id() {
  if [[ -n "${GPR_MODEL:-}" ]]; then
    printf '%s' "$GPR_MODEL"
    return
  fi
  case "$1" in
    claude) printf 'claude-opus-4-7' ;;
    codex)  printf 'gpt-5-codex' ;;
    *)      printf 'default' ;;
  esac
}

# Dispatch by name. echo synthesises a signal locally; everything else
# routes through the generic binary-invocation path.
agent_run() {
  local agent="$1" stream_log="$2" timeout_sec="${3:-1800}"
  if [[ "$agent" == "echo" ]]; then
    _agent_run_echo "$stream_log"
    return $?
  fi
  if ! agent_supports "$agent"; then
    log_fail "unknown agent: $agent"
    return 2
  fi
  _agent_run_generic "$agent" "$stream_log" "$timeout_sec"
}

# --- internals ----------------------------------------------------------------

# Print the argv (one element per line) for an agent: binary first, then
# flags. Caller reads into an array and appends the prompt.
_agent_argv() {
  case "$1" in
    claude)
      # Note: do NOT add `--append-system-prompt` here without a value.
      # That flag consumes the next positional, which would swallow the
      # rendered prompt and leave Claude with nothing to do (wall=0s,
      # no signal block). The continuation prompt template already
      # includes everything the agent needs.
      printf 'claude\n--print\n--output-format\nstream-json\n--verbose\n--dangerously-skip-permissions\n'
      ;;
    codex)
      printf 'codex\nexec\n--dangerously-bypass-approvals-and-sandbox\n--json\n'
      ;;
    opencode)
      printf 'opencode\nrun\n--no-confirm\n'
      ;;
    gemini)
      printf 'gemini\n--yolo\n--prompt\n'
      ;;
    *) return 1 ;;
  esac
}

# Generic binary-invocation path. Reads the prompt on stdin, looks up
# argv via _agent_argv, runs under `timeout`, tees stream output. Prints
# raw stdout to its caller.
_agent_run_generic() {
  local agent="$1" stream_log="$2" timeout_sec="$3"
  local argv=()
  while IFS= read -r line; do
    argv+=("$line")
  done < <(_agent_argv "$agent")
  local binary="${argv[0]}"
  if ! command -v "$binary" >/dev/null 2>&1; then
    log_fail "$binary CLI not found on PATH"
    return 127
  fi
  # Append user-supplied extra args (skills/MCP/allowedTools/etc).
  if [[ -n "${GPR_AGENT_EXTRA_ARGS:-}" ]]; then
    local extra=()
    # shellcheck disable=SC2086
    eval "extra=(${GPR_AGENT_EXTRA_ARGS})"
    argv+=("${extra[@]}")
  fi
  local prompt
  prompt="$(cat)"
  local raw
  raw="$(timeout "$timeout_sec" "${argv[@]}" "$prompt" 2>&1 | tee "$stream_log")"
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
