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

# gpr confidence-audit [--agent X] [--max-attempts N]
# Loops the confidence auditor against Plan.json until verdict.confident or
# max-attempts (default 3) is hit. Returns 0 if confident, non-zero if not.
cmd_confidence_audit() {
  local agent="${GPR_AUDIT_AGENT:-${GPR_AGENT:-claude}}"
  local max_attempts=3
  while (( $# > 0 )); do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --max-attempts) max_attempts="$2"; shift 2 ;;
      -h|--help)
        echo "gpr confidence-audit [--agent X] [--max-attempts N]"
        return 0 ;;
      *) log_fail "unknown arg: $1"; return 2 ;;
    esac
  done
  banner "gpr confidence-audit" "agent=$agent  max-attempts=$max_attempts"
  hr
  source "$GPR_LIB/agents.sh"
  local attempt=1
  while (( attempt <= max_attempts )); do
    log_info "attempt $attempt of $max_attempts"
    local prompt
    prompt=$(python3 -m lib.cli render-confidence-prompt)
    local stream_log; stream_log=$(mktemp)
    local out
    out=$(printf '%s' "$prompt" | agent_run "$agent" "$stream_log" 600)
    rm -f "$stream_log"
    set +e
    local verdict_json
    verdict_json=$(printf '%s' "$out" | python3 -m lib.cli ingest-confidence --stdin --json 2>&1)
    local rc=$?
    set -e
    if (( rc == 0 )); then
      log_ok "confident — Plan is ready"
      return 0
    fi
    local rec
    rec=$(printf '%s' "$verdict_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('recommendation','?'))" 2>/dev/null || echo "?")
    log_warn "verdict: not confident (recommendation=$rec)"
    if [[ "$rec" == "rewrite_plan" ]]; then
      log_warn "recommend full rewrite — see .gpr/Steer.md and rerun /gpr-grill"
      return 3
    fi
    printf '%s' "$verdict_json" | python3 -c "
import sys, json
v = json.load(sys.stdin)
for l in v.get('loopholes', []):
    print(f\"  [{l.get('category','?')}] {l.get('problem','')}\")
    print(f\"    fix: {l.get('fix','')}\")"
    log_dim "(automatic Plan revision is roadmapped; for now, edit Plan.json manually based on the fixes above and re-run)"
    attempt=$(( attempt + 1 ))
  done
  log_warn "confidence-audit did not converge after $max_attempts attempts"
  return 4
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
