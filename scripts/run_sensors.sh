#!/usr/bin/env bash
# Run the sensors (dead code, unused libraries, latency, error rate) and build reports/health-report.{json,md}.
#   bash scripts/run_sensors.sh                 # local only
#   APP_URL=https://... bash scripts/run_sensors.sh   # also measure the live deployment
# No -e on purpose: sensors are expected to find problems, and the run must keep going.
set -uo pipefail
cd "$(dirname "$0")/.."

# Collapsible log sections in GitHub Actions; plain headings when run locally.
group() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::group::$1"; else echo; echo "== $1"; fi; }
endgroup() { if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::endgroup::"; fi; }

# Which Python to use, and the port for the private copy of the app.
PY="${PYTHON:-python}"
PORT="${PORT:-8765}"
DURATION="${DURATION:-15}"

group "0/5 Setup"
echo "What: prepare an empty reports/ folder and print the settings for this run."
echo "Commit:        ${GITHUB_SHA:-local}"
echo "Python:        $("$PY" --version 2>&1)"
echo "Load test:     ${DURATION}s per target (2 users on 'Load 5000 people', 3 on person lookups)"
echo "Live site:     ${APP_URL:-(not set, only the private copy is tested)}"
# Start from an empty reports/ so old results never mix in.
mkdir -p reports
rm -f reports/*.json reports/*.txt reports/*.log reports/*.md
endgroup

group "1/5 Sensor: dead code (vulture)"
echo "What: list Python code in app/ and api/ that is defined but never used."
"$PY" -m vulture app api --min-confidence 60 --ignore-decorators "@router.*,@app.*" --ignore-names "row_factory" > reports/vulture.txt 2>/dev/null || true
if [ -s reports/vulture.txt ]; then echo "Found:"; sed 's/^/  /' reports/vulture.txt; else echo "Found: nothing unused in Python."; fi
echo "(Unused JavaScript files and unused libraries are checked in step 5.)"
endgroup

group "2/5 Start a private copy of the app on port $PORT"
echo "What: run the same app on this machine, so its log shows which queries are slow."
# Start a private copy of the app in the background; its log (with slow queries) goes to app.log.
"$PY" -m uvicorn api.index:app --port "$PORT" --log-level warning > reports/app.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
# Wait up to 10 seconds until it answers.
ready=no
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; then ready=yes; break; fi
  sleep 0.2
done
echo "Ready: $ready (after $i check(s))"
endgroup

group "3/5 Sensors: latency + error rate on the private copy (${DURATION}s)"
echo "What: 5 simulated users hit the private copy; every request is timed and its status recorded."
"$PY" scripts/collect_runtime.py --base-url "http://127.0.0.1:$PORT" --duration "$DURATION" --out reports/runtime-local.json
kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null
slow=$(grep -c 'slow query' reports/app.log 2>/dev/null); echo "Slow queries logged by the app: ${slow:-0}"
endgroup

group "4/5 Sensors: latency + error rate on the live site"
if [ -n "${APP_URL:-}" ]; then
  echo "What: the same load test against $APP_URL. These numbers decide pass or fail."
  "$PY" scripts/collect_runtime.py --base-url "$APP_URL" --duration "$DURATION" --out reports/runtime-live.json || echo "Live load test failed; the report will use the private copy's numbers."
else
  echo "Skipped: APP_URL is not set, so the report uses the private copy's numbers."
fi
endgroup

group "5/5 Report: compare every result with budgets.json"
echo "What: run the 4 checks, decide healthy or not, and write reports/health-report.json and .md."
"$PY" scripts/build_report.py
endgroup
