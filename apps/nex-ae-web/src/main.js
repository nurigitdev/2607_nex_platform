const services = [
  ["nex-oa", 8101],
  ["nex-ag", 8102],
  ["nex-ae-api", 8103],
  ["nex-cx", 8104],
  ["nex-mo", 8105]
];

const serviceList = document.querySelector("#service-list");
const statusStrip = document.querySelector("#status-strip");
const refreshButton = document.querySelector("#refresh-button");

refreshButton.addEventListener("click", () => {
  renderServiceStatuses();
});

renderServiceStatuses();

async function renderServiceStatuses() {
  serviceList.innerHTML = "";
  statusStrip.innerHTML = "";

  const results = await Promise.all(services.map(readService));
  for (const result of results) {
    serviceList.appendChild(createServiceRow(result));
    statusStrip.appendChild(createStatusDot(result));
  }
}

async function readService([serviceId, port]) {
  const baseUrl = `http://127.0.0.1:${port}`;
  const result = { serviceId, port, health: "UNKNOWN", ready: "UNKNOWN", version: "unknown" };

  try {
    const [health, ready, version] = await Promise.all([
      readJson(`${baseUrl}/health`),
      readJson(`${baseUrl}/ready`),
      readJson(`${baseUrl}/version`)
    ]);
    result.health = health.health_status || "UNKNOWN";
    result.ready = ready.readiness_status || "UNKNOWN";
    result.version = version.version || "unknown";
  } catch {
    result.health = "UNHEALTHY";
    result.ready = "NOT_READY";
  }

  return result;
}

async function readJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function createServiceRow(result) {
  const row = document.createElement("article");
  row.className = "service-row";
  row.innerHTML = `
    <div>
      <strong>${result.serviceId}</strong>
      <span>:${result.port} · ${result.version}</span>
    </div>
    <div class="badge-pair">
      <span class="badge ${badgeClass(result.health)}">${result.health}</span>
      <span class="badge ${badgeClass(result.ready)}">${result.ready}</span>
    </div>
  `;
  return row;
}

function createStatusDot(result) {
  const dot = document.createElement("span");
  dot.className = `status-dot ${badgeClass(result.ready)}`;
  dot.title = `${result.serviceId}: ${result.ready}`;
  dot.setAttribute("aria-label", `${result.serviceId} ${result.ready}`);
  return dot;
}

function badgeClass(status) {
  if (status === "HEALTHY" || status === "READY") return "success";
  if (status === "DEGRADED" || status === "LOW_CONFIDENCE") return "warning";
  if (status === "RUNNING") return "running";
  if (status === "PENDING" || status === "UNKNOWN") return "pending";
  return "danger";
}
