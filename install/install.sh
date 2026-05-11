#!/usr/bin/env bash
# Install gpr Claude Code skill and slash commands into ~/.claude/.
set -euo pipefail

GPR_HOME="${GPR_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
INSTALL_SRC="$GPR_HOME/install"
TARGET_SKILL_DIR="${HOME}/.claude/skills/gpr"
TARGET_CMD_DIR="${HOME}/.claude/commands"

# shellcheck source=lib/term.sh
source "$GPR_HOME/lib/term.sh"

banner "gpr install" "Claude Code skill + slash commands"
hr

mkdir -p "$TARGET_SKILL_DIR" "$TARGET_CMD_DIR"

cp "$INSTALL_SRC/skill/SKILL.md" "$TARGET_SKILL_DIR/SKILL.md"
log_ok "skill: $TARGET_SKILL_DIR/SKILL.md"

GRILL_TARGET="${HOME}/.claude/skills/gpr-grill"
mkdir -p "$GRILL_TARGET"
cp "$INSTALL_SRC/skill/gpr-grill/SKILL.md" "$GRILL_TARGET/SKILL.md"
log_ok "skill: $GRILL_TARGET/SKILL.md"

SETTINGS_TARGET="${HOME}/.claude/skills/gpr-settings"
mkdir -p "$SETTINGS_TARGET"
cp "$INSTALL_SRC/skill/gpr-settings/SKILL.md" "$SETTINGS_TARGET/SKILL.md"
log_ok "skill: $SETTINGS_TARGET/SKILL.md"

for f in "$INSTALL_SRC"/commands/*.md; do
  cp "$f" "$TARGET_CMD_DIR/"
  log_ok "command: $TARGET_CMD_DIR/$(basename "$f")"
done

if ! command -v gpr >/dev/null 2>&1; then
  hr
  log_warn "gpr not on PATH yet"
  log_info "add a symlink: ln -sf '$GPR_HOME/bin/gpr' \$(brew --prefix)/bin/gpr"
  log_info "or: ln -sf '$GPR_HOME/bin/gpr' ~/.local/bin/gpr"
fi

hr
log_ok "installed"
log_info "from any Claude Code session in a gpr-initialized project, type:"
printf '    %s/gpr%s             run one iteration\n' "$C_BOLD" "$C_RESET"
printf '    %s/gpr-status%s      show progress\n' "$C_BOLD" "$C_RESET"
printf '    %s/gpr-steer%s ...   write a human steer\n' "$C_BOLD" "$C_RESET"
printf '    %s/gpr-settings%s    browse/edit gpr config\n' "$C_BOLD" "$C_RESET"
