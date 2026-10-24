// Fetch JSON and read the timing headers the API adds to every response.
// Call an API path, time the round trip and read X-DB-Queries.
// Returns { ok, status, body, elapsed, queries }; body is null when the reply is not JSON.
async function apiGet(path) {
  const started = performance.now();
  const response = await fetch(path);
  const elapsed = Math.round(performance.now() - started);
  const queries = Number(response.headers.get("X-DB-Queries") || 0);
  let body = null;
  try {
    body = await response.json();
  } catch (e) {
    body = null;
  }
  return { ok: response.ok, status: response.status, body, elapsed, queries };
}

// Draw the three pills: response time, DB query count and HTTP status (green, amber or red).
function renderMetrics(el, result) {
  const speed = result.elapsed > 500 ? "bad" : result.elapsed > 200 ? "warn" : "good";
  const queries = result.queries > 10 ? "bad" : "good";
  el.innerHTML =
    `<span class="pill ${speed}">${result.elapsed} ms</span>` +
    `<span class="pill ${queries}">${result.queries} DB queries</span>` +
    `<span class="pill ${result.ok ? "good" : "bad"}">HTTP ${result.status}</span>`;
}

// Make text safe to insert as HTML, so data can never run as code.
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
