# shellcheck shell=bash
# Bash helpers for commit-intent / pr-description / confidence-audit
# workflows. Sourced by bin/gpr.
#
# Each of these subcommands runs the same three-step machine:
#
#   1. Render a prompt via `gpr render-X-prompt`.
#   2. Pipe it to `agent_run` to invoke the configured agent.
#   3. Pipe the agent's output to `gpr ingest-X` to parse the
#      structured trailer block + apply side effects.
#
# _run_prompt_channel is that machine, factored once. Each public
# subcommand below is a thin caller that names the render command,
# the ingest command, and the agent. Adding a fourth such workflow
# (e.g. release-notes) becomes a 5-line dispatcher.

# _run_prompt_channel <render-cmd> <ingest-cmd> <agent> <timeout> [render-args... | -- ingest-args...]
#
# Tokens before `--` are passed to the render command; tokens after
# `--` are passed to the ingest command. The pipe between them is
# always: render-stdout → agent_run → ingest-stdin.
#
# Threads ${GPR_PLAN:-default} into both the render and ingest calls so
# every commit-intent / pr-description / confidence-audit invocation
# targets the active plan.
_run_prompt_channel() {
  local render_cmd="$1" ingest_cmd="$2" agent="$3" timeout_sec="$4"
  shift 4
  local render_args=()
  local ingest_args=()
  local seen_dash=0
  for a in "$@"; do
    if (( seen_dash == 0 )) && [[ "$a" == "--" ]]; then
      seen_dash=1
      continue
    fi
    if (( seen_dash == 0 )); then
      render_args+=("$a")
    else
      ingest_args+=("$a")
    fi
  done
  # shellcheck source=lib/agents.sh
  source "$GPR_LIB/agents.sh"
  local plan_slug="${GPR_PLAN:-default}"
  local prompt
  prompt=$(python3 -m lib.cli "$render_cmd" --plan "$plan_slug" "${render_args[@]}")
  local stream_log
  stream_log=$(mktemp)
  local out
  out=$(printf '%s' "$prompt" | agent_run "$agent" "$stream_log" "$timeout_sec")
  rm -f "$stream_log"
  printf '%s' "$out" | python3 -m lib.cli "$ingest_cmd" --stdin --plan "$plan_slug" "${ingest_args[@]}"
}

# gpr commit-intent <ID> [--agent X] [--apply]
cmd_commit_intent() {
  local intent_id="" agent="${GPR_COMMIT_AGENT:-${GPR_AGENT:-claude}}"
  local ingest_extra=()
  while (( $# > 0 )); do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --apply) ingest_extra+=("--apply"); shift ;;
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
  _run_prompt_channel render-commit-prompt ingest-commit "$agent" 300 \
    --intent "$intent_id" -- "${ingest_extra[@]}"
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
    set +e
    local verdict_json
    verdict_json=$(_run_prompt_channel render-confidence-prompt ingest-confidence "$agent" 600 -- --json 2>&1)
    local rc=$?
    set -e
    if (( rc == 0 )); then
      log_ok "confident — Plan is ready"
      return 0
    fi
    local rec
    rec=$(printf '%s' "$verdict_json" | jq -r '.recommendation // "?"' 2>/dev/null || echo "?")
    log_warn "verdict: not confident (recommendation=$rec)"
    if [[ "$rec" == "rewrite_plan" ]]; then
      log_warn "recommend full rewrite — see Steer.md (in active plan dir) and rerun /gpr-grill"
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
  local agent="${GPR_COMMIT_AGENT:-${GPR_AGENT:-claude}}"
  local ingest_extra=()
  while (( $# > 0 )); do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --output) ingest_extra+=("--output" "$2"); shift 2 ;;
      -h|--help)
        echo "gpr pr-description [--agent X] [--output PATH]"
        return 0 ;;
      *) log_fail "unknown arg: $1"; return 2 ;;
    esac
  done
  banner "gpr pr-description" "agent=$agent"
  hr
  _run_prompt_channel render-pr-prompt ingest-pr "$agent" 600 \
    -- "${ingest_extra[@]}"
}
