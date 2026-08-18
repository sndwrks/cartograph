#!/bin/sh
# Symlink the cartograph agent-board skill into a Claude skills directory.
# usage: ./scripts/install-skill.sh [skills-dir]        (default: ~/.claude/skills)
set -e

SKILLS_DIR="${1:-$HOME/.claude/skills}"
SKILL_SRC="$(cd "$(dirname "$0")/../skills/agent-board" && pwd)"

[ -f "$SKILL_SRC/SKILL.md" ] || {
    echo "skill not found: $SKILL_SRC/SKILL.md" >&2
    exit 1
}

mkdir -p "$SKILLS_DIR"
ln -sfn "$SKILL_SRC" "$SKILLS_DIR/agent-board"
echo "installed: $SKILLS_DIR/agent-board -> $SKILL_SRC"
echo "restart or start a new session for the skill to be listed"
