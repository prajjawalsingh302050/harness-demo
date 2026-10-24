#!/usr/bin/env bash
# Run the sensors (dead code, unused libraries, latency, error rate) and build reports/health-report.{json,md}.
#   bash scripts/run_sensors.sh                 # local only
#   APP_URL=https://... bash scripts/run_sensors.sh   # also measure the live deployment
# No -e on purpose: sensors are expected to find problems, and the run must keep going.
set -uo pipefail
cd "$(dirname "$0")/.."

# Which Python to use, and the port for the private copy of the app.
PY="${PYTHON:-python}"
PORT="${PORT:-8765}"
# Start from an empty reports/ so old results never mix in.
mkdir -p reports
rm -f reports/*.json reports/*.txt reports/*.log reports/*.md

echo "== Drift sensor: dead code"
"$PY" -m vulture app api --min-confidence 60 --ignore-decorators "@router.*,@app.*" --ignore-names "row_factory" > reports/vulture.txt 2>/dev/null || true

echo "== Runtime sensors (local)"
# Start a private copy of the app in the background; its log (with slow queries) goes to app.log.
"$PY" -m uvicorn api.index:app --port "$PORT" --log-level warning > reports/app.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
# Wait up to 10 seconds until it answers.
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.2
done
# Load-test the private copy, then stop it.
"$PY" scripts/collect_runtime.py --base-url "http://127.0.0.1:$PORT" --duration "${DURATION:-15}" --out reports/runtime-local.json
kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null

# If a live URL is set, run the same load test against it.
if [ -n "${APP_URL:-}" ]; then
  echo "== Runtime sensors (live: $APP_URL)"
  "$PY" scripts/collect_runtime.py --base-url "$APP_URL" --duration "${DURATION:-15}" --out reports/runtime-live.json || true
fi

# Judge everything against budgets.json and write the report.
echo "== Report"
"$PY" scripts/build_report.py
