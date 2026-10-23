const checksEl = document.getElementById("checks");
const overallEl = document.getElementById("overall");
const generatedEl = document.getElementById("generated");
const historyEl = document.getElementById("history");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function getJson(name) {
  const response = await fetch(`${REPORTS_API}/${name}?ref=${REPORTS_REF}`, {
    headers: { Accept: "application/vnd.github.raw+json" },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadReport() {
  try {
    const report = await getJson("latest.json");
    overallEl.innerHTML = report.healthy
      ? '<span class="pill good">All checks pass</span>'
      : `<span class="pill bad">${report.failed} check(s) failing</span>`;
    generatedEl.textContent = `Generated ${new Date(report.generated_at).toLocaleString()}`;
    checksEl.innerHTML = report.checks.map((c) => `
      <tr>
        <td>${esc(c.name)}</td>
        <td><span class="kind ${esc(c.kind)}">${esc(c.kind.toUpperCase())}</span></td>
        <td>${esc(c.area)}</td>
        <td class="num">${esc(c.value)}</td>
        <td class="num">${esc(c.budget)}</td>
        <td>${c.ok ? '<span class="pill good">Pass</span>' : '<span class="pill bad">Fail</span>'}</td>
      </tr>`).join("");
  } catch (e) {
    checksEl.innerHTML = '<tr><td colspan="6" class="muted">No report yet. Run the health-check workflow in GitHub Actions.</td></tr>';
  }

  try {
    const history = await getJson("history.json");
    historyEl.innerHTML = history.map((h) =>
      `<span class="${h.healthy ? "ok" : "fail"}" title="${esc(new Date(h.generated_at).toLocaleString())}: ${h.healthy ? "healthy" : esc(h.failed) + " failing"}"></span>`
    ).join("");
  } catch (e) {
    historyEl.innerHTML = '<span class="muted">No history yet.</span>';
  }
}

loadReport();
