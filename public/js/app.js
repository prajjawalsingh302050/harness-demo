let page = 1;

const tbody = document.getElementById("orders");
const label = document.getElementById("page-label");
const metrics = document.getElementById("metrics");
const prev = document.getElementById("prev");
const rupees = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

async function loadOrders() {
  tbody.innerHTML = '<tr><td colspan="6" class="muted">Loading…</td></tr>';
  label.textContent = `Page ${page}`;
  prev.disabled = page === 1;

  const result = await apiGet(`/api/orders?page=${page}`);
  renderMetrics(metrics, result);

  if (!result.ok || !result.body) {
    tbody.innerHTML = `<tr><td colspan="6" class="error">Failed to load orders (HTTP ${result.status})</td></tr>`;
    return;
  }

  tbody.innerHTML = result.body.orders.map((o) => `
    <tr>
      <td>#${o.id}</td>
      <td>${escapeHtml(o.customer)}</td>
      <td>${escapeHtml(o.city)}</td>
      <td>${escapeHtml(o.created_at)}</td>
      <td class="status">${escapeHtml(o.status)}</td>
      <td class="num">${rupees.format(o.total)}</td>
    </tr>`).join("");
}

prev.addEventListener("click", () => { page = Math.max(1, page - 1); loadOrders(); });
document.getElementById("next").addEventListener("click", () => { page += 1; loadOrders(); });

loadOrders();
