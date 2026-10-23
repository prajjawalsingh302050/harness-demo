const form = document.getElementById("lookup");
const input = document.getElementById("person-id");
const card = document.getElementById("person");
const metrics = document.getElementById("metrics");

async function loadPerson(id) {
  card.innerHTML = '<p class="muted">Loading…</p>';
  const result = await apiGet(`/api/people/${encodeURIComponent(id)}`);
  renderMetrics(metrics, result);

  if (result.status === 404) {
    card.innerHTML = `<p class="muted">No person with ID ${escapeHtml(id)}.</p>`;
    return;
  }
  if (!result.ok || !result.body) {
    card.innerHTML = `<p class="error">Something went wrong (HTTP ${result.status}).</p>`;
    return;
  }

  const p = result.body;
  card.innerHTML = `
    <table>
      <tr><th>Name</th><td>${escapeHtml(p.name)}</td></tr>
      <tr><th>Email</th><td>${escapeHtml(p.email)}</td></tr>
      <tr><th>City</th><td>${escapeHtml(p.city)}</td></tr>
    </table>`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  history.replaceState(null, "", `?id=${encodeURIComponent(input.value)}`);
  loadPerson(input.value);
});

const initial = new URLSearchParams(location.search).get("id") || "1";
input.value = initial;
loadPerson(initial);
