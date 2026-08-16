#!/bin/sh
# Symlink the codegraph post-commit hook into a target repository.
# usage: ./scripts/install-hook.sh /path/to/target-repo
set -e

TARGET="${1:?usage: install-hook.sh <target-repo-path>}"
HOOK_SRC="$(cd "$(dirname "$0")" && pwd)/post-commit"
GIT_DIR="$(git -C "$TARGET" rev-parse --git-dir 2>/dev/null)" || {
    echo "not a git repository: $TARGET" >&2
    exit 1
}
case "$GIT_DIR" in
    /*) HOOKS_DIR="$GIT_DIR/hooks" ;;
    *) HOOKS_DIR="$TARGET/$GIT_DIR/hooks" ;;
esac
mkdir -p "$HOOKS_DIR"
ln -sf "$HOOK_SRC" "$HOOKS_DIR/post-commit"
echo "installed: $HOOKS_DIR/post-commit -> $HOOK_SRC"
echo "set CODEGRAPH_COMPOSE_DIR and CODEGRAPH_REPO if the defaults don't fit"
