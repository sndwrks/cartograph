#!/bin/sh
# Symlink every cartograph skill into a Claude skills directory.
# usage: ./scripts/install-skill.sh [skills-dir]        (default: ~/.claude/skills)
set -e

SKILLS_DIR="${1:-$HOME/.claude/skills}"
SRC_ROOT="$(cd "$(dirname "$0")/../skills" && pwd)"

mkdir -p "$SKILLS_DIR"

installed=0
for skill in "$SRC_ROOT"/*/; do
    name="$(basename "$skill")"
    [ -f "$skill/SKILL.md" ] || {
        echo "skipping $name: no SKILL.md" >&2
        continue
    }
    ln -sfn "${skill%/}" "$SKILLS_DIR/$name"
    echo "installed: $SKILLS_DIR/$name -> ${skill%/}"
    installed=$((installed + 1))
done

[ "$installed" -gt 0 ] || {
    echo "no skills found under $SRC_ROOT" >&2
    exit 1
}

echo "restart or start a new session for the skills to be listed"
