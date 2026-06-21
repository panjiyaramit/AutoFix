#!/usr/bin/env bash
# reset.sh — re-arms the demo for another run
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Clearing backend log..."
> "$SCRIPT_DIR/backend/logs/app.log"

echo "==> Deleting autopilot fix branches..."
cd "$SCRIPT_DIR/backend"
git branch -r | grep "autopilot/fix-" | sed 's|origin/||' | while read branch; do
  git push origin --delete "$branch" 2>/dev/null && echo "    Deleted $branch" || true
done

echo "==> Done. Demo is reset."
