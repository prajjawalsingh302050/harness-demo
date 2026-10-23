const form = document.getElementById("lookup");
const input = document.getElementById("user-id");
const card = document.getElementById("user");
const metrics = document.getElementById("metrics");

async function loadUser(id) {
  card.innerHTML = '<p class="muted">Loading…</p>';
  const result = await apiGet(`/api/users/${encodeURIComponent(id)}`);
  renderMetrics(metrics, result);

  if (result.status === 404) {
    card.innerHTML = `<p class="muted">No customer with ID ${escapeHtml(id)}.</p>`;
    return;
  }
  if (!result.ok || !result.body) {
    card.innerHTML = `<p class="error">Something went wrong (HTTP ${result.status}).</p>`;
    return;
  }

  const u = result.body;
  card.innerHTML = `
    <table>
      <tr><th>Name</th><td>${escapeHtml(u.name)}</td></tr>
      <tr><th>Email</th><td>${escapeHtml(u.email)}</td></tr>
      <tr><th>City</th><td>${escapeHtml(u.city)}</td></tr>
      <tr><th>Orders</th><td>${u.order_count}</td></tr>
    </table>`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  history.replaceState(null, "", `?id=${encodeURIComponent(input.value)}`);
  loadUser(input.value);
});

const initial = new URLSearchParams(location.search).get("id") || "1";
input.value = initial;
loadUser(initial);
