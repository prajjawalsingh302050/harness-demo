const liveMetrics = document.getElementById("live-metrics");
const liveBody = document.getElementById("live-body");

document.getElementById("repo-link").href = REPO_URL;

document.querySelectorAll("button[data-path]").forEach((button) => {
  button.addEventListener("click", async () => {
    liveBody.textContent = "Loading…";
    const result = await apiGet(button.dataset.path);
    renderMetrics(liveMetrics, result);
    const text = JSON.stringify(result.body, null, 2) || "(no JSON body)";
    liveBody.textContent = text.length > 1500 ? text.slice(0, 1500) + "\n…" : text;
  });
});
