#!/usr/bin/env bash
# Re-plant every problem (restore app code to the demo-start tag) through a PR, so the demo can run again.
set -euo pipefail
cd "$(dirname "$0")/.."

PATHS="app api tests migrations public requirements.txt data"
BRANCH="demo/reset-$(date +%Y%m%d-%H%M%S)"

git fetch -q origin main --tags
git checkout -q -b "$BRANCH" origin/main

# Remove files that were added after demo-start (e.g. new migrations), then restore the tagged versions.
for f in $(git diff --name-only --diff-filter=A demo-start HEAD -- $PATHS); do git rm -q "$f"; done
git checkout demo-start -- $PATHS

if git diff --cached --quiet; then
  echo "Already in the demo-start state. Nothing to reset."
  git checkout -q main && git branch -q -D "$BRANCH"
  exit 0
fi

git commit -qm "Reset demo: re-plant drift and runtime problems"
git push -q origin "$BRANCH"
gh pr create --base main --head "$BRANCH" --title "Reset demo to planted state" \
  --body "Restores \`$PATHS\` to the \`demo-start\` tag so the harness demo can run again. Merge, wait for Vercel, then run **health-check**."
git checkout -q main
