# shellcheck shell=bash
# Terminal styling: colors, spinners, hr, box-drawing.
# Uses raw ANSI; no external deps. Auto-disables on non-TTY / NO_COLOR.

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  __TTY=1
else
  __TTY=0
fi

if (( __TTY )); then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_BOLD=$'\033[1m'
  C_RED=$'\033[38;5;203m'
  C_GREEN=$'\033[38;5;114m'
  C_YELLOW=$'\033[38;5;221m'
  C_BLUE=$'\033[38;5;111m'
  C_MAGENTA=$'\033[38;5;176m'
  C_CYAN=$'\033[38;5;116m'
  C_GRAY=$'\033[38;5;245m'
  C_WHITE=$'\033[38;5;255m'
  C_ORANGE=$'\033[38;5;215m'
else
  C_RESET=''; C_DIM=''; C_BOLD=''
  C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''
  C_MAGENTA=''; C_CYAN=''; C_GRAY=''; C_WHITE=''; C_ORANGE=''
fi

# Print a horizontal rule the width of the terminal.
hr() {
  local cols=${COLUMNS:-$(tput cols 2>/dev/null || echo 80)}
  local ch="${1:-─}"
  printf '%s' "$C_GRAY"
  printf "%${cols}s" '' | tr ' ' "$ch"
  printf '%s\n' "$C_RESET"
}

# Banner: 2-line header with title + tagline.
banner() {
  local title="$1"
  local tagline="${2:-}"
  printf '%s%s%s%s\n' "$C_BOLD" "$C_WHITE" "$title" "$C_RESET"
  if [[ -n "$tagline" ]]; then
    printf '%s%s%s\n' "$C_GRAY" "$tagline" "$C_RESET"
  fi
}

# Status glyphs (no emoji per design).
glyph_ok()    { printf '%s+%s' "$C_GREEN" "$C_RESET"; }
glyph_fail()  { printf '%sx%s' "$C_RED" "$C_RESET"; }
glyph_warn()  { printf '%s!%s' "$C_YELLOW" "$C_RESET"; }
glyph_dot()   { printf '%so%s' "$C_BLUE" "$C_RESET"; }
glyph_arrow() { printf '%s>%s' "$C_CYAN" "$C_RESET"; }
glyph_pipe()  { printf '%s|%s' "$C_GRAY" "$C_RESET"; }

log_info()  { printf '  %s %s\n' "$(glyph_arrow)" "$*"; }
log_ok()    { printf '  %s %s\n' "$(glyph_ok)" "$*"; }
log_warn()  { printf '  %s %s\n' "$(glyph_warn)" "$*"; }
log_fail()  { printf '  %s %s\n' "$(glyph_fail)" "$*" >&2; }
log_dim()   { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

# Spinner: writes status frames in-place. Usage:
#   spinner_start "Working"
#   ...do thing...
#   spinner_stop ok|fail|warn "Done"
__SPINNER_PID=0
__SPINNER_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

spinner_start() {
  if (( ! __TTY )); then
    printf '%s ...\n' "$1"
    return 0
  fi
  local msg="$1"
  (
    local i=0
    while :; do
      printf '\r  %s%s%s %s' "$C_CYAN" "${__SPINNER_FRAMES[i]}" "$C_RESET" "$msg"
      i=$(( (i+1) % ${#__SPINNER_FRAMES[@]} ))
      sleep 0.08
    done
  ) &
  __SPINNER_PID=$!
  disown $__SPINNER_PID 2>/dev/null || true
}

spinner_stop() {
  if (( ! __TTY )); then
    return 0
  fi
  if [[ $__SPINNER_PID -gt 0 ]] && kill -0 "$__SPINNER_PID" 2>/dev/null; then
    kill "$__SPINNER_PID" 2>/dev/null
    wait "$__SPINNER_PID" 2>/dev/null || true
  fi
  __SPINNER_PID=0
  local kind="$1" msg="${2:-}"
  local g
  case "$kind" in
    ok)   g=$(glyph_ok) ;;
    fail) g=$(glyph_fail) ;;
    warn) g=$(glyph_warn) ;;
    *)    g=$(glyph_dot) ;;
  esac
  printf '\r  %s %s\033[K\n' "$g" "$msg"
}

# Render a status table row: label (left, padded), value (right, colored).
row() {
  local label="$1" value="$2" color="${3:-$C_WHITE}"
  printf '  %s%-22s%s %s%s%s\n' "$C_GRAY" "$label" "$C_RESET" "$color" "$value" "$C_RESET"
}

# Print a small progress bar. Usage: bar <fraction 0..1> [width=24]
bar() {
  local frac="$1"
  local width="${2:-24}"
  awk -v f="$frac" -v w="$width" -v g="$C_GREEN" -v y="$C_YELLOW" -v r="$C_RED" -v dim="$C_DIM" -v rs="$C_RESET" '
    BEGIN {
      if (f < 0) f = 0; if (f > 1) f = 1;
      filled = int(f * w + 0.5);
      empty = w - filled;
      col = (f < 0.6) ? g : (f < 0.95) ? y : r;
      printf "%s[%s", dim, rs;
      printf "%s", col;
      for (i=0;i<filled;i++) printf "█";
      printf "%s", rs;
      printf "%s", dim;
      for (i=0;i<empty;i++) printf "░";
      printf "]%s", rs;
    }'
}

# Format a duration in seconds to "Xh Ym" / "Xm Ys" / "Xs".
fmt_duration() {
  local s="$1"
  awk -v s="$s" 'BEGIN {
    s = int(s);
    if (s >= 3600) printf "%dh %dm", s/3600, (s%3600)/60;
    else if (s >= 60) printf "%dm %ds", s/60, s%60;
    else printf "%ds", s;
  }'
}

# Format an integer with thousand separators.
fmt_int() {
  awk -v n="$1" 'BEGIN {
    s = sprintf("%d", n); r = "";
    while (length(s) > 3) { r = "," substr(s, length(s)-2) r; s = substr(s, 1, length(s)-3); }
    print s r;
  }'
}

# Format a USD amount.
fmt_usd() {
  awk -v n="$1" 'BEGIN { printf "$%.2f", n }'
}
