# shellcheck shell=bash
# The main loop. Wired up by bin/gpr's `run` subcommand.
#
# loop_iteration is now a composition of named stages. Each stage has
# a small contract: which files it reads/writes, which globals it sets,
# what return codes mean. Stages are sourceable + testable individually
# from a bash repl with stub PWD.
#
# Stage globals (set by stages, read by callers in the same iter):
#   INTENT_ID, INTENT_TITLE, AGENT_WALL, SIG_STATUS, AUDIT_ALL_PASS,
#   STALLED. All cleared at the top of loop_iteration.
#
# Stage return codes carry meaning to loop_iteration's case dispatch.

# shellcheck source=lib/term.sh
# shellcheck source=lib/agents.sh
# shellcheck source=lib/notify.sh

GPR_LIB="${GPR_LIB:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
# shellcheck disable=SC1091
source "$GPR_LIB/term.sh"
# shellcheck disable=SC1091
source "$GPR_LIB/agents.sh"
# shellcheck disable=SC1091
source "$GPR_LIB/notify.sh"

# --- stages -------------------------------------------------------------------

# Stage 1: disk-space pre-check. Returns 8 on disk-full, 0 otherwise.
iter_disk_check() {
  local free_kb
  free_kb=$(df -k . | awk 'NR==2 {print $4}')
  if (( free_kb < 1048576 )); then
    log_fail "less than 1GB free; aborting iteration"
    return 8
  fi
  return 0
}

# Stage 2: log a notice if Steer.md is non-empty. The continuation prompt
# template handles the actual steer behaviour; this is human-visible only.
iter_steer_log() {
  if [[ -s ".gpr/Steer.md" ]]; then
    log_warn "Steer.md non-empty — agent will handle steer this iter"
  fi
}

# Stage 3: pick the next intent (mutates Plan.json under fcntl).
# Sets INTENT_ID, INTENT_TITLE on success.
# Returns 0 (ok), 9 (no open intents — caller treats as done attempt),
#         1 (next-intent command failed).
iter_pick_intent() {
  local next_json
  if ! next_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli next-intent --json 2>&1); then
    if echo "$next_json" | grep -q '"no_open_intents"'; then
      log_ok "no open intents — checking final completion"
      return 9
    fi
    log_fail "next-intent failed: $next_json"
    return 1
  fi
  INTENT_ID=$(echo "$next_json" | jq -r '.intent.id')
  INTENT_TITLE=$(echo "$next_json" | jq -r '.intent.title')
  return 0
}

# Stage 4: render the continuation prompt to <iter_dir>/prompt.md.
iter_render_prompt() {
  local iter_dir="$1" intent_id="$2"
  if ! GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli render-prompt --intent "$intent_id" \
       > "$iter_dir/prompt.md"; then
    log_fail "render-prompt failed"
    return 1
  fi
  return 0
}

# Stage 5: spawn the agent. Writes stream.log, stdout.log, stderr.log.
# Sets AGENT_WALL (seconds elapsed). Returns 0 if loop should continue,
# regardless of the agent's exit code: timeout and non-zero exit both
# leave the intent in_progress for next round.
iter_invoke_agent() {
  local agent="$1" iter_dir="$2" iter_timeout="$3" iter="$4"
  local stream_log="$iter_dir/stream.log"
  local stdout_log="$iter_dir/stdout.log"
  local stderr_log="$iter_dir/stderr.log"
  local model_id
  model_id=$(agent_model_id "$agent")

  spinner_start "agent=$agent model=$model_id  (iter $iter)"
  local start_ts end_ts
  start_ts=$(date +%s)
  set +e
  agent_run "$agent" "$stream_log" "$iter_timeout" < "$iter_dir/prompt.md" \
    > "$stdout_log" 2> "$stderr_log"
  local agent_rc=$?
  set -e
  end_ts=$(date +%s)
  AGENT_WALL=$(( end_ts - start_ts ))

  if (( agent_rc == 124 )); then
    spinner_stop fail "agent timed out after ${iter_timeout}s"
    log_warn "agent timeout — leaving intent in-progress; will retry next iter"
    notify timeout "gpr timeout" "agent $agent timed out on intent $INTENT_ID"
    return 0
  elif (( agent_rc != 0 )); then
    spinner_stop fail "agent exited rc=$agent_rc (wall=${AGENT_WALL}s)"
    log_dim "stderr tail: $(tail -n 3 "$stderr_log" | tr '\n' '|')"
    return 0
  fi
  spinner_stop ok "agent done (wall=${AGENT_WALL}s)"
  return 0
}

# Stage 6: parse token usage from the stream log and record a budget tick.
iter_record_budget() {
  local agent="$1" iter_dir="$2" model_id="$3"
  local tokens_in=0 tokens_out=0
  if [[ "$agent" != "echo" ]]; then
    local usage
    usage=$(GPR_PROJECT_ROOT="$PWD" python3 -c "
import sys; sys.path.insert(0, '$GPR_LIB/..')
from lib.state import budget
lines = open('$iter_dir/stream.log').read().splitlines()
i, o = budget.parse_usage('$agent', lines)
print(f'{i} {o}')")
    read -r tokens_in tokens_out <<< "$usage"
  fi
  GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli record-budget \
    --agent "$agent" --model "$model_id" \
    --tokens-input "${tokens_in:-0}" --tokens-output "${tokens_out:-0}" \
    --wall-seconds "$AGENT_WALL" --json > "$iter_dir/budget.json"
}

# Stage 7: ingest the agent's signal block, run Layer-1 audit if status=done.
# Sets SIG_STATUS, AUDIT_ALL_PASS. Returns 0 always (errors handled inline).
iter_ingest_signal() {
  local iter_dir="$1" intent_id="$2"
  local ingest_json
  ingest_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli ingest-signal \
    --stdin --intent "$intent_id" --json < "$iter_dir/stdout.log" 2>&1) || {
      log_fail "ingest-signal failed: $ingest_json"
      SIG_STATUS="progress"
      AUDIT_ALL_PASS="false"
      return 0
    }
  echo "$ingest_json" > "$iter_dir/signal.json"
  SIG_STATUS=$(echo "$ingest_json" | jq -r '.signal.status')
  AUDIT_ALL_PASS=$(echo "$ingest_json" | jq -r 'if .audit and .audit.all_pass then "true" else "false" end')
  log_info "signal: ${C_BOLD}${SIG_STATUS}${C_RESET}"

  local audit_summary
  audit_summary=$(echo "$ingest_json" | python3 -c "
import sys, json
d = json.load(sys.stdin); a = d.get('audit')
if a is None: print('no-audit')
else: print(f\"audit: {a['pass']}/{a['pass']+a['fail']+a['manual']} pass, all_pass={a['all_pass']}\")")
  if [[ "$audit_summary" != "no-audit" ]]; then
    log_info "$audit_summary"
  fi
}

# Stage 8: Layer-2 cross-model audit on done-flips when --deep-audit. Reverts
# the intent to open if the auditor's verdict is fail.
iter_layer2_audit() {
  local agent="$1" iter_dir="$2" intent_id="$3"
  if [[ "$SIG_STATUS" != "done" || "$AUDIT_ALL_PASS" != "true" ]]; then
    return 0
  fi
  if [[ "${GPR_DEEP_AUDIT:-0}" != "1" ]]; then
    return 0
  fi
  local audit_agent="${GPR_AUDIT_AGENT:-$agent}"
  log_info "Layer-2 audit (agent=$audit_agent)"
  cp "$iter_dir/signal.json" "$iter_dir/audit.json"
  local audit_prompt_path="$iter_dir/layer2-prompt.md"
  GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli render-audit-prompt \
    --intent "$intent_id" --audit-json "$iter_dir/audit.json" \
    > "$audit_prompt_path"
  local layer2_stream="$iter_dir/layer2-stream.log"
  spinner_start "Layer-2 verifier ($audit_agent)"
  set +e
  local layer2_out
  layer2_out=$(agent_run "$audit_agent" "$layer2_stream" 600 < "$audit_prompt_path")
  local layer2_rc=$?
  set -e
  if (( layer2_rc != 0 )); then
    spinner_stop warn "Layer-2 agent rc=$layer2_rc; treating as inconclusive"
    return 0
  fi
  spinner_stop ok "Layer-2 done"
  set +e
  local verdict_json
  verdict_json=$(echo "$layer2_out" | GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli \
    ingest-audit-verdict --intent "$intent_id" --stdin --json 2>&1)
  local v_rc=$?
  set -e
  echo "$verdict_json" > "$iter_dir/layer2-verdict.json"
  if (( v_rc != 0 )); then
    log_warn "Layer-2 audit FAILED — intent reverted to open"
    notify layer2 "gpr Layer-2 fail" "intent $intent_id reverted by cross-model verifier"
  else
    log_ok "Layer-2 verdict: pass"
  fi
}

# Stage 9: update the stalemate signature (payload-hash + checkbox count).
# Sets STALLED ("true" / "false").
iter_signature() {
  local sig_json
  sig_json=$(GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli record-signature --json)
  STALLED=$(echo "$sig_json" | jq -r '.stalled')
}

# Stage 10: classify the agent's signal into a return code.
# Returns 0 (continue), 2 (blocked), 3 (decide), 7 (rescope).
iter_classify_signal() {
  local intent_id="$1"
  case "$SIG_STATUS" in
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
  return 0
}

# Stage 11: stalemate kill-switch. Returns 6 if N consecutive iters showed
# the same signature.
iter_check_stalemate() {
  if [[ "$STALLED" == "True" || "$STALLED" == "true" ]]; then
    log_warn "STALEMATE — 4 iterations with no signature change"
    notify stalemate "gpr stalemate" "no progress for 4 iters"
    return 6
  fi
  return 0
}

# Stage 12: budget hard-stop. Returns 4 if the binding axis is exhausted.
iter_check_budget_hardstop() {
  local iter_dir="$1"
  local hard_stop
  hard_stop=$(jq -r '.hard_stop' < "$iter_dir/budget.json" 2>/dev/null || echo false)
  if [[ "$hard_stop" == "True" || "$hard_stop" == "true" ]]; then
    log_warn "BUDGET HARD STOP"
    notify budget "gpr budget" "hard stop reached"
    return 4
  fi
  return 0
}

# --- iteration composition ----------------------------------------------------

# Run a single iteration. Composes stages above. Returns:
#   0 = continue, 2 = blocked, 3 = decide, 4 = budget_limited,
#   5 = unmet_zero_progress, 6 = unmet_stalemate, 7 = rescope,
#   8 = unmet_disk_full, 9 = no-open-intents (all-done attempt).
loop_iteration() {
  local agent="$1" iter="$2" run_dir="$3" iter_timeout="${4:-1800}"

  local iter_dir
  iter_dir="$run_dir/iter-$(printf '%04d' "$iter")"
  mkdir -p "$iter_dir"

  # Reset stage outputs.
  INTENT_ID=""; INTENT_TITLE=""; AGENT_WALL=0
  SIG_STATUS=""; AUDIT_ALL_PASS="false"; STALLED="false"

  iter_disk_check || return $?
  iter_steer_log

  local rc
  set +e
  iter_pick_intent
  rc=$?
  set -e
  if (( rc != 0 )); then return $rc; fi
  log_info "iter $iter — intent ${C_BOLD}${INTENT_ID}${C_RESET} ${C_GRAY}${INTENT_TITLE}${C_RESET}"

  iter_render_prompt "$iter_dir" "$INTENT_ID" || return $?

  iter_invoke_agent "$agent" "$iter_dir" "$iter_timeout" "$iter"
  iter_record_budget "$agent" "$iter_dir" "$(agent_model_id "$agent")"
  iter_ingest_signal "$iter_dir" "$INTENT_ID"
  iter_layer2_audit "$agent" "$iter_dir" "$INTENT_ID"
  iter_signature

  set +e
  iter_classify_signal "$INTENT_ID"
  rc=$?
  set -e
  if (( rc != 0 )); then return $rc; fi

  iter_check_stalemate || return $?
  iter_check_budget_hardstop "$iter_dir" || return $?

  return 0
}

# --- top-level run loop -------------------------------------------------------

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

  local i rc
  for (( i = 1; i <= max_iters; i++ )); do
    hr
    set +e
    loop_iteration "$agent" "$i" "$run_dir" "$iter_timeout"
    rc=$?
    set -e
    case $rc in
      0) ;;
      9)
        log_ok "all intents done — running reverse audit"
        if loop_reverse_audit "$run_dir"; then
          log_ok "reverse audit clean — achieved"
          return 0
        else
          log_warn "reverse audit found issues; continuing loop"
          continue
        fi
        ;;
      *)
        return $rc
        ;;
    esac
  done
  log_warn "max iterations reached ($max_iters)"
  return 5
}

# Run the reverse-audit (spec-drift sweep) before declaring achieved.
# Returns 0 if clean (achieved), non-zero if regressions/gaps found.
loop_reverse_audit() {
  local run_dir="$1"
  local agent="${GPR_AUDIT_AGENT:-${GPR_AGENT:-claude}}"
  if [[ "$agent" == "echo" ]]; then
    log_dim "skipping reverse audit (echo agent)"
    return 0
  fi
  local prompt_path="$run_dir/reverse-audit-prompt.md"
  GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli render-reverse-prompt > "$prompt_path"
  local stream="$run_dir/reverse-audit-stream.log"
  spinner_start "reverse audit ($agent)"
  set +e
  local out
  out=$(agent_run "$agent" "$stream" 900 < "$prompt_path")
  local rc=$?
  set -e
  spinner_stop ok "reverse audit done"
  if (( rc != 0 )); then
    log_warn "reverse-audit agent rc=$rc; treating as not-clean"
    return 1
  fi
  local verdict_json
  set +e
  verdict_json=$(echo "$out" | GPR_PROJECT_ROOT="$PWD" python3 -m lib.cli \
    ingest-reverse-verdict --stdin --json 2>&1)
  local v_rc=$?
  set -e
  echo "$verdict_json" > "$run_dir/reverse-audit.json"
  return $v_rc
}
