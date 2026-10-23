#!/usr/bin/env bash
# Publish reports/health-report.json to the health-reports branch (latest.json + history.json).
# The /health.html page reads from that branch.
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH=health-reports
TMP="$(mktemp -d)"

if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch -q origin "$BRANCH"
  git worktree add -q -B "$BRANCH" "$TMP" "origin/$BRANCH"
else
  git worktree add -q --detach "$TMP"
  (cd "$TMP" && git checkout -q --orphan "$BRANCH" && git rm -rqf .)
fi

python3 - "$TMP" <<'EOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
report = json.loads(Path("reports/health-report.json").read_text())
(out / "latest.json").write_text(json.dumps(report, indent=2))
history_file = out / "history.json"
history = json.loads(history_file.read_text()) if history_file.exists() else []
history.append({k: report[k] for k in ("generated_at", "commit", "healthy", "failed")})
history_file.write_text(json.dumps(history[-100:], indent=2))
EOF

cd "$TMP"
git add latest.json history.json
git -c user.name="harness-sensors" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -qm "Health report $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -q origin "HEAD:$BRANCH"
cd - >/dev/null
git worktree remove --force "$TMP"
echo "Published health report to branch $BRANCH"
