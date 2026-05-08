# shellcheck shell=bash
# The main loop. Wired up by bin/gpr's `run` subcommand.

# shellcheck source=lib/term.sh
# shellcheck source=lib/agents.sh
# shellcheck source=lib/notify.sh

GPR_LIB="${GPR_LIB:-/Users/aditya/Developer/gpr/lib}"
# shellcheck disable=SC1091
source "$GPR_LIB/term.sh"
# shellcheck disable=SC1091
source "$GPR_LIB/agents.sh"
# shellcheck disable=SC1091
source "$GPR_LIB/notify.sh"

# Run a single iteration. Echoes summary to stdout. Returns:
#   0 = continue, 2 = blocked, 3 = decide, 4 = budget_limited,
#   5 = unmet_zero_progress, 6 = unmet_stalemate, 7 = rescope, 8 = unmet_disk_full
loop_iteration() {
  local agent="$1" iter="$2" run_dir="$3" iter_timeout="${4:-1800}"

  local iter_dir="$run_dir/iter-$(printf '%04d' "$iter")"
  mkdir -p "$iter_dir"

  # 1. Disk-space pre-check (need ≥ 1GB free).
  local free_kb
  free_kb=$(df -k . | awk 'NR==2 {print $4}')
  if (( free_kb < 1048576 )); then
    log_fail "less than 1GB free; aborting iteration"
    return 8
  fi

  # 2. Steer.md FIRST. If non-empty, treat this iter as a steer-handler turn.
  local steer_text=""
  if [[ -s ".gpr/Steer.md" ]]; then
    steer_text=$(cat .gpr/Steer.md)
    log_warn "Steer.md non-empty — agent will handle steer this iter"
  fi

  # 3. Pick next intent (mutates Plan.json with in_progress).
  local next_json
  if ! next_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli next-intent --json 2>&1); then
    if echo "$next_json" | grep -q '"no_open_intents"'; then
      log_ok "no open intents — checking final completion"
      return 9  # caller treats 9 as "all-done attempt"
    fi
    log_fail "next-intent failed: $next_json"
    return 1
  fi
  local intent_id
  intent_id=$(echo "$next_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['intent']['id'])")
  local intent_title
  intent_title=$(echo "$next_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['intent']['title'])")
  log_info "iter $iter — intent ${C_BOLD}${intent_id}${C_RESET} ${C_GRAY}${intent_title}${C_RESET}"

  # 4. Render the continuation prompt to iter_dir/prompt.md.
  local prompt_path="$iter_dir/prompt.md"
  if ! GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli render-prompt --intent "$intent_id" > "$prompt_path"; then
    log_fail "render-prompt failed"
    return 1
  fi

  # 5. Spawn the agent. Stream goes to iter_dir/stream.log; raw stdout captured.
  local stream_log="$iter_dir/stream.log"
  local stdout_log="$iter_dir/stdout.log"
  local stderr_log="$iter_dir/stderr.log"
  local model_id
  model_id=$(agent_model_id "$agent")

  spinner_start "agent=$agent model=$model_id  (iter $iter)"
  local start_ts end_ts wall
  start_ts=$(date +%s)
  set +e
  agent_run "$agent" "$stream_log" "$iter_timeout" < "$prompt_path" \
    > "$stdout_log" 2> "$stderr_log"
  local agent_rc=$?
  set -e
  end_ts=$(date +%s)
  wall=$(( end_ts - start_ts ))
  if (( agent_rc == 124 )); then
    spinner_stop fail "agent timed out after ${iter_timeout}s"
    log_warn "agent timeout — leaving intent in-progress; will retry next iter"
    notify timeout "gpr timeout" "agent $agent timed out on intent $intent_id"
    return 0
  elif (( agent_rc != 0 )); then
    spinner_stop fail "agent exited rc=$agent_rc (wall=${wall}s)"
    log_dim "stderr tail: $(tail -n 3 "$stderr_log" | tr '\n' '|')"
    return 0
  fi
  spinner_stop ok "agent done (wall=${wall}s)"

  # 6. Token accounting.
  local tokens_in tokens_out
  tokens_in=0; tokens_out=0
  if [[ "$agent" != "echo" ]]; then
    local usage
    usage=$(GPR_PROJECT_ROOT="$PWD" python3 -c "
import sys; sys.path.insert(0, '$GPR_LIB/..');
from lib.state import budget
lines = open('$stream_log').read().splitlines()
i, o = budget.parse_usage('$agent', lines)
print(f'{i} {o}')")
    read -r tokens_in tokens_out <<< "$usage"
  fi
  GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli record-budget \
    --agent "$agent" --model "$model_id" \
    --tokens-input "${tokens_in:-0}" --tokens-output "${tokens_out:-0}" \
    --wall-seconds "$wall" --json > "$iter_dir/budget.json"

  # 7. Ingest signal — runs audit if status=done.
  local ingest_json
  ingest_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli ingest-signal \
    --stdin --intent "$intent_id" --json < "$stdout_log" 2>&1) || {
      log_fail "ingest-signal failed: $ingest_json"
      return 0
    }
  echo "$ingest_json" > "$iter_dir/signal.json"
  local sig_status
  sig_status=$(echo "$ingest_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['signal']['status'])")
  log_info "signal: ${C_BOLD}$sig_status${C_RESET}"

  # 8. Audit summary.
  local audit_summary
  audit_summary=$(echo "$ingest_json" | python3 -c "
import sys, json
d = json.load(sys.stdin); a = d.get('audit')
if a is None: print('no-audit')
else: print(f\"audit: {a['pass']}/{a['pass']+a['fail']+a['manual']} pass, all_pass={a['all_pass']}\")")
  if [[ "$audit_summary" != "no-audit" ]]; then
    log_info "$audit_summary"
  fi

  # 9. Stalemate signature update.
  local sig_json
  sig_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli record-signature --json)
  local stalled
  stalled=$(echo "$sig_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['stalled'])")

  # 10. Classify by signal.
  case "$sig_status" in
    done)
      log_ok "intent $intent_id audit passed — marked done"
      return 0
      ;;
    blocked)
      log_warn "BLOCKED — leaving for human"
      notify blocked "gpr blocked" "intent $intent_id blocked"
      return 2
      ;;
    decide)
      log_warn "DECIDE — question written to .gpr/Steer.md"
      notify decide "gpr question" "intent $intent_id needs decision"
      return 3
      ;;
    rescope)
      log_warn "RESCOPE — proposed plan rewrite written to .gpr/Steer.md"
      notify rescope "gpr rescope" "agent proposed plan rewrite"
      return 7
      ;;
  esac

  # 11. Stalemate?
  if [[ "$stalled" == "True" ]]; then
    log_warn "STALEMATE — 4 iterations with no signature change"
    notify stalemate "gpr stalemate" "no progress for 4 iters"
    return 6
  fi

  # 12. Budget hard-stop?
  local budget_status
  budget_status=$(cat "$iter_dir/budget.json")
  local hard_stop
  hard_stop=$(echo "$budget_status" | python3 -c "import sys,json; print(json.load(sys.stdin)['hard_stop'])" 2>/dev/null || echo False)
  if [[ "$hard_stop" == "True" ]]; then
    log_warn "BUDGET HARD STOP"
    notify budget "gpr budget" "hard stop reached"
    return 4
  fi

  return 0
}

# Top-level run loop.
loop_run() {
  local agent="${GPR_AGENT:-claude}"
  local max_iters="${GPR_MAX_ITERS:-50}"
  local iter_timeout="${GPR_ITER_TIMEOUT:-1800}"

  if [[ ! -f .gpr/Plan.json ]]; then
    log_fail "no .gpr/Plan.json — run 'gpr init' first"
    return 1
  fi

  local run_id
  run_id="$(date +%Y%m%d-%H%M%S)-$$"
  local run_dir=".gpr/runs/$run_id"
  mkdir -p "$run_dir"
  log_info "run id: ${C_BOLD}$run_id${C_RESET}"

  local i
  for (( i = 1; i <= max_iters; i++ )); do
    hr
    local rc
    set +e
    loop_iteration "$agent" "$i" "$run_dir" "$iter_timeout"
    rc=$?
    set -e
    case $rc in
      0) ;;
      9)
        log_ok "all intents done — running final audit"
        return 0
        ;;
      *)
        return $rc
        ;;
    esac
  done
  log_warn "max iterations reached ($max_iters)"
  return 5
}
