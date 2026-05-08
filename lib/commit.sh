# shellcheck shell=bash
# Bash helpers for commit-intent and pr-description workflows.
# Sourced by bin/gpr.

# gpr commit-intent <ID> [--agent X] [--apply]
# Asks the agent to write a conventional-commit message for the iteration's
# diff, then prints (or applies) it.
cmd_commit_intent() {
  local intent_id="" agent="${GPR_COMMIT_AGENT:-${GPR_AGENT:-claude}}" apply=""
  while (( $# > 0 )); do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --apply) apply="--apply"; shift ;;
      -h|--help)
        echo "gpr commit-intent <ID> [--agent X] [--apply]"
        return 0 ;;
      *)
        if [[ -z "$intent_id" ]]; then intent_id="$1"; shift
        else log_fail "unknown arg: $1"; return 2
        fi ;;
    esac
  done
  if [[ -z "$intent_id" ]]; then
    log_fail "intent id required"
    return 2
  fi
  banner "gpr commit-intent" "intent=$intent_id agent=$agent"
  hr
  local prompt
  prompt=$(python3 -m lib.cli render-commit-prompt --intent "$intent_id")
  # shellcheck source=lib/agents.sh
  source "$GPR_LIB/agents.sh"
  local stream_log; stream_log=$(mktemp)
  local out
  out=$(printf '%s' "$prompt" | agent_run "$agent" "$stream_log" 300)
  rm -f "$stream_log"
  printf '%s' "$out" | python3 -m lib.cli ingest-commit --stdin $apply
}

# gpr pr-description [--agent X] [--output PATH]
cmd_pr_description() {
  local agent="${GPR_COMMIT_AGENT:-${GPR_AGENT:-claude}}" output=""
  while (( $# > 0 )); do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --output) output="$2"; shift 2 ;;
      -h|--help)
        echo "gpr pr-description [--agent X] [--output PATH]"
        return 0 ;;
      *) log_fail "unknown arg: $1"; return 2 ;;
    esac
  done
  banner "gpr pr-description" "agent=$agent"
  hr
  local prompt
  prompt=$(python3 -m lib.cli render-pr-prompt)
  source "$GPR_LIB/agents.sh"
  local stream_log; stream_log=$(mktemp)
  local out
  out=$(printf '%s' "$prompt" | agent_run "$agent" "$stream_log" 600)
  rm -f "$stream_log"
  local args=(--stdin)
  [[ -n "$output" ]] && args+=(--output "$output")
  printf '%s' "$out" | python3 -m lib.cli ingest-pr "${args[@]}"
}
