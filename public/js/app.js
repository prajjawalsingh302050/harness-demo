// People page: loads 50 or 5000 people into the table and shows the timing pills.
const tbody = document.getElementById("people");
const count = document.getElementById("count");
const metrics = document.getElementById("metrics");

// Fetch `limit` people from the API and render them as table rows.
async function loadPeople(limit) {
  tbody.innerHTML = '<tr><td colspan="4" class="muted">Loading…</td></tr>';
  count.textContent = "";

  const result = await apiGet(`/api/people?limit=${limit}`);
  renderMetrics(metrics, result);

  if (!result.ok || !result.body) {
    tbody.innerHTML = `<tr><td colspan="4" class="error">Failed to load people (HTTP ${result.status})</td></tr>`;
    return;
  }

  count.textContent = `${result.body.count} people`;
  tbody.innerHTML = result.body.people.map((p) => `
    <tr>
      <td>${p.id}</td>
      <td>${escapeHtml(p.name)}</td>
      <td>${escapeHtml(p.email)}</td>
      <td>${escapeHtml(p.city)}</td>
    </tr>`).join("");
}

// Each button carries its limit in data-limit.
document.querySelectorAll("button[data-limit]").forEach((button) => {
  button.addEventListener("click", () => loadPeople(button.dataset.limit));
});

loadPeople(50);
