const numberFormatter = new Intl.NumberFormat("en-US");

function qs(id) {
  return document.getElementById(id);
}

function toMinutes(seconds) {
  if (!seconds || seconds <= 0) {
    return "0m";
  }

  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins <= 0) {
    return `${secs}s`;
  }
  if (secs === 0) {
    return `${mins}m`;
  }
  return `${mins}m ${secs}s`;
}

function safe(text) {
  if (!text) {
    return "-";
  }
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

function drawDailyChart(rows) {
  const canvas = qs("dailyChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth;
  const height = 300;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.clearRect(0, 0, width, height);
  if (!rows || rows.length === 0) {
    ctx.fillStyle = "#5f6c71";
    ctx.font = "14px IBM Plex Sans";
    ctx.fillText("No data yet", 12, 24);
    return;
  }

  const pad = { top: 20, right: 36, bottom: 44, left: 46 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxChars = Math.max(10, ...rows.map((row) => row.total_chars));
  const maxCpm = Math.max(10, ...rows.map((row) => row.cpm));

  ctx.strokeStyle = "#d8d0c5";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, pad.top + plotH);
  ctx.lineTo(pad.left + plotW, pad.top + plotH);
  ctx.stroke();

  const count = rows.length;
  const slotW = plotW / count;
  const barW = Math.max(4, slotW * 0.62);

  rows.forEach((row, index) => {
    const x = pad.left + index * slotW + (slotW - barW) / 2;
    const y = pad.top + plotH - (row.total_chars / maxChars) * plotH;
    const h = pad.top + plotH - y;

    const gradient = ctx.createLinearGradient(0, y, 0, y + h + 10);
    gradient.addColorStop(0, "#00a097");
    gradient.addColorStop(1, "#83ddd2");
    ctx.fillStyle = gradient;
    ctx.fillRect(x, y, barW, h);
  });

  ctx.strokeStyle = "#d26b2f";
  ctx.lineWidth = 2;
  ctx.beginPath();

  rows.forEach((row, index) => {
    const x = pad.left + index * slotW + slotW / 2;
    const y = pad.top + plotH - (row.cpm / maxCpm) * plotH;
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  ctx.fillStyle = "#d26b2f";
  rows.forEach((row, index) => {
    const x = pad.left + index * slotW + slotW / 2;
    const y = pad.top + plotH - (row.cpm / maxCpm) * plotH;
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#526166";
  ctx.font = "11px IBM Plex Sans";
  const step = Math.max(1, Math.floor(rows.length / 7));
  rows.forEach((row, index) => {
    if (index % step !== 0 && index !== rows.length - 1) {
      return;
    }
    const x = pad.left + index * slotW + slotW / 2;
    const day = row.date.slice(5);
    ctx.fillText(day, x - 16, height - 14);
  });

  ctx.fillStyle = "#3d4f54";
  ctx.font = "12px IBM Plex Sans";
  ctx.fillText(`chars max ${Math.round(maxChars)}`, pad.left + 6, pad.top + 14);
  ctx.fillStyle = "#a55821";
  ctx.fillText(`cpm max ${Math.round(maxCpm)}`, pad.left + 150, pad.top + 14);
}

function renderSessions(rows) {
  const body = qs("sessionsBody");
  if (!rows || rows.length === 0) {
    body.innerHTML = '<tr><td colspan="4">No sessions in this window.</td></tr>';
    return;
  }

  body.innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td class="mono">${safe(row.start_iso)}</td>
        <td>${numberFormatter.format(row.chars)}</td>
        <td>${row.cpm}</td>
        <td>${toMinutes(row.duration_seconds)}</td>
      </tr>
    `
    )
    .join("");
}

function renderEvents(rows) {
  const body = qs("eventsBody");
  if (!rows || rows.length === 0) {
    body.innerHTML = '<tr><td colspan="4">No events in this window.</td></tr>';
    return;
  }

  body.innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td class="mono">${safe(row.iso)}</td>
        <td>${numberFormatter.format(row.chars)}</td>
        <td><span class="tag">${safe(row.schema || "-")}</span></td>
        <td>${safe(row.text || "-")}</td>
      </tr>
    `
    )
    .join("");
}

function applySummary(summary) {
  qs("kpiChars").textContent = numberFormatter.format(summary.total_chars || 0);
  qs("kpiCpm").textContent = String(summary.cpm || 0);
  qs("kpiActive").textContent = toMinutes(summary.active_seconds || 0);
  qs("kpiSessions").textContent = numberFormatter.format(summary.session_count || 0);
}

async function refresh() {
  const days = Number(qs("days").value || "7");
  qs("meta").textContent = "Loading...";

  try {
    const [meta, summary, daily, sessions, events] = await Promise.all([
      fetchJson("/api/meta"),
      fetchJson(`/api/summary?days=${days}`),
      fetchJson(`/api/daily?days=${Math.max(7, days)}`),
      fetchJson(`/api/sessions?days=${days}&limit=25`),
      fetchJson(`/api/events?days=${days}&limit=80`),
    ]);

    applySummary(summary);
    drawDailyChart(daily.rows || []);
    renderSessions(sessions.rows || []);
    renderEvents(events.rows || []);

    const stamp = new Date().toLocaleString();
    qs("meta").textContent = `Data file: ${meta.data_file} | events: ${meta.event_count} | updated: ${stamp}`;
  } catch (error) {
    qs("meta").textContent = `Failed to load data: ${String(error)}`;
  }
}

qs("refresh").addEventListener("click", refresh);
qs("days").addEventListener("change", refresh);
window.addEventListener("resize", () => {
  refresh();
});

refresh();
