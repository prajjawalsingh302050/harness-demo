// Fetch JSON and read the timing headers the API adds to every response.
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

function renderMetrics(el, result) {
  const speed = result.elapsed > 500 ? "bad" : result.elapsed > 200 ? "warn" : "good";
  const queries = result.queries > 10 ? "bad" : "good";
  el.innerHTML =
    `<span class="pill ${speed}">${result.elapsed} ms</span>` +
    `<span class="pill ${queries}">${result.queries} DB queries</span>` +
    `<span class="pill ${result.ok ? "good" : "bad"}">HTTP ${result.status}</span>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
