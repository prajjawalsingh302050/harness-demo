// Sales charts from the 2024 dashboard. The page that loaded this was removed.
function drawSalesChart(canvas, points) {
  const ctx = canvas.getContext("2d");
  const max = Math.max(...points);
  ctx.beginPath();
  points.forEach((value, i) => {
    const x = (i / (points.length - 1)) * canvas.width;
    const y = canvas.height - (value / max) * canvas.height;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function formatLakh(value) {
  return `${(value / 100000).toFixed(1)} L`;
}
