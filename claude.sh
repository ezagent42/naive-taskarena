#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env into environment
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  echo "ERROR: .env not found. Run 'uv run taskarena init' first." >&2
  exit 1
fi

# Session name
SESSION="taskarena"

# Reattach if session exists
if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Start new tmux session with Claude Code + TaskArena channel
# Note: TaskArena loads .env via python-dotenv internally, so tmux env inheritance is not required.
# We source .env in this script only for any shell-level tooling that may need it.
tmux new-session -d -s "$SESSION" \
  "cd $SCRIPT_DIR && claude --dangerously-load-development-channels server:taskarena"
exec tmux attach -t "$SESSION"