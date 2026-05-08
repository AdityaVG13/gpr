# shellcheck shell=bash
# Cross-platform desktop notifications. macOS via osascript, Linux via
# notify-send, Windows (Git Bash / MSYS / WSL) via powershell.exe toast,
# everywhere else no-op. Rate-limited to one notification per kind per
# 60s using lock files in /tmp.

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
  local kernel
  kernel="$(uname -s)"
  case "$kernel" in
    Darwin)
      local script
      printf -v script 'display notification %s with title %s' \
        "\"${body//\"/\\\"}\"" "\"${title//\"/\\\"}\""
      osascript -e "$script" >/dev/null 2>&1 || true
      ;;
    Linux)
      # WSL: try notify-send first, fall through to powershell.exe.
      if command -v notify-send >/dev/null 2>&1; then
        notify-send "$title" "$body" 2>/dev/null || true
      elif grep -qi microsoft /proc/version 2>/dev/null && command -v powershell.exe >/dev/null 2>&1; then
        _notify_windows_toast "$title" "$body"
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*)
      _notify_windows_toast "$title" "$body"
      ;;
  esac
}

# Windows toast via powershell.exe (System.Windows.Forms balloon).
# Works under Git Bash, MSYS, Cygwin, and WSL when powershell.exe is on PATH.
_notify_windows_toast() {
  local title="$1" body="$2"
  command -v powershell.exe >/dev/null 2>&1 || return 0
  local safe_title="${title//\"/\\\"}"
  local safe_body="${body//\"/\\\"}"
  powershell.exe -NoProfile -Command "
    Add-Type -AssemblyName System.Windows.Forms;
    \$ni = New-Object System.Windows.Forms.NotifyIcon;
    \$ni.Icon = [System.Drawing.SystemIcons]::Information;
    \$ni.BalloonTipTitle = \"$safe_title\";
    \$ni.BalloonTipText = \"$safe_body\";
    \$ni.Visible = \$true;
    \$ni.ShowBalloonTip(5000);
    Start-Sleep -Milliseconds 5500;
    \$ni.Dispose();
  " >/dev/null 2>&1 &
  disown 2>/dev/null || true
}
