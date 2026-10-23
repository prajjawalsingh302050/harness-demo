#!/usr/bin/env bash
# Run every sensor and build reports/health-report.{json,md}.
#   bash scripts/run_sensors.sh                 # local only
#   APP_URL=https://... bash scripts/run_sensors.sh   # also measure the live deployment
set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python}"
PORT="${PORT:-8765}"
mkdir -p reports
rm -f reports/*.json reports/*.txt reports/*.log reports/*.md

echo "== Codebase sensors"
"$PY" -m pip_audit -r requirements.txt -f json -o reports/pip-audit.json --progress-spinner off >/dev/null 2>&1 || true
"$PY" -m vulture app api --min-confidence 60 --ignore-decorators "@router.*,@app.*" --ignore-names "row_factory" > reports/vulture.txt 2>/dev/null || true
"$PY" -m pytest -q -p no:cacheprovider --cov=app --cov-report=json:reports/coverage.json > reports/pytest.txt 2>&1 || true

echo "== Runtime sensors (local)"
"$PY" -m uvicorn api.index:app --port "$PORT" --log-level warning > reports/app.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.2
done
"$PY" scripts/collect_runtime.py --base-url "http://127.0.0.1:$PORT" --duration "${DURATION:-15}" --out reports/runtime-local.json
kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null

if [ -n "${APP_URL:-}" ]; then
  echo "== Runtime sensors (live: $APP_URL)"
  "$PY" scripts/collect_runtime.py --base-url "$APP_URL" --duration "${DURATION:-15}" --out reports/runtime-live.json || true
fi

echo "== Report"
"$PY" scripts/build_report.py
