# shellcheck shell=bash
# Cross-platform desktop notifications. macOS via osascript, linux via
# notify-send, otherwise no-op. Rate-limited to one notification per kind
# per 60s using lock files in /tmp.

NOTIFY_RATE_LIMIT_SECONDS="${NOTIFY_RATE_LIMIT_SECONDS:-60}"

_notify_should_fire() {
  local kind="$1"
  local key
  key="gpr-notify-$(echo "$kind" | tr -c '[:alnum:]' '_')"
  local marker="/tmp/${key}"
  local now
  now=$(date +%s)
  if [[ -f "$marker" ]]; then
    local last
    last=$(cat "$marker" 2>/dev/null || echo 0)
    if (( now - last < NOTIFY_RATE_LIMIT_SECONDS )); then
      return 1
    fi
  fi
  echo "$now" > "$marker"
  return 0
}

notify() {
  # Smoke-test guard: echo agent runs are dry-runs, never notify.
  if [[ "${GPR_AGENT:-}" == "echo" ]]; then
    return 0
  fi
  # Explicit kill-switch for users who never want desktop notifications.
  if [[ "${GPR_NO_NOTIFY:-}" == "1" ]]; then
    return 0
  fi
  local kind="$1" title="$2" body="$3"
  if ! _notify_should_fire "$kind"; then
    return 0
  fi
  case "$(uname -s)" in
    Darwin)
      local script
      printf -v script 'display notification %s with title %s' \
        "\"${body//\"/\\\"}\"" "\"${title//\"/\\\"}\""
      osascript -e "$script" >/dev/null 2>&1 || true
      ;;
    Linux)
      if command -v notify-send >/dev/null 2>&1; then
        notify-send "$title" "$body" 2>/dev/null || true
      fi
      ;;
  esac
}
