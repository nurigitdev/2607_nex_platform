import {
  createMockDocumentDetailClient,
  documentDetailRoute
} from "./documentDetailClient.js";

const services = [
  ["nex-oa", 8101],
  ["nex-ag", 8102],
  ["nex-ae-api", 8103],
  ["nex-cx", 8104],
  ["nex-mo", 8105]
];

const baseProgressEvents = [
  ["generation.request.accepted", "INTAKE", "RUNNING"],
  ["generation.retrieval.ready", "CONTEXT_PACKAGED", "RUNNING"],
  ["generation.prompt.packaged", "PROMPT_ASSEMBLING", "RUNNING"],
  ["generation.provider.completed", "GENERATING", "RUNNING"],
  ["generation.draft.validating", "DRAFT_VALIDATING", "RUNNING"],
  ["generation.citation.validating", "CITATION_VALIDATING", "RUNNING"],
  ["generation.completed", "COMPLETED", "COMPLETED"]
];

const localOwnerScope = {
  tenantId: "tenant-local",
  ownerUserId: "owner-local"
};

const workspaceState = {
  workspaceId: "workspace-local",
  chatDocumentId: "chat-doc-local",
  interactionId: "interaction-local",
  cxGenerationId: "cx-gen-local",
  retrievalPackageId: "cx-ret-local",
  artifactHandoffId: "handoff-local",
  selectedDocumentId: "doc-001",
  artifactRef: {
    artifactId: "artifact-local",
    artifactVersionId: "artifact-version-local-001",
    displayTitle: "MVP 착수 패키지 보고서",
    artifactType: "generated_document",
    artifactStatus: "READY",
    primaryFormat: "MD",
    availableFormats: ["MD"],
    previewRoute: "/api/v1/artifact-files/artifact-file-local-001/preview",
    downloadRoutes: {
      MD: "/api/v1/artifact-files/artifact-file-local-001/download"
    },
    sourceGenerationId: "cx-gen-local",
    sourceContentHash: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    qualitySummary: {
      citationStatus: "VALIDATED",
      citationCount: 3,
      evidenceRefCount: 3,
      groundingRequired: true
    },
    actions: ["preview", "view_sources", "view_lineage", "download_md"]
  },
  documents: [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      projectionSchemaVersion: "ae_document_detail_projection.v1",
      detailRoute: documentDetailRoute("doc-001"),
      ownerScope: localOwnerScope,
      sourceService: "nex-cx",
      sourceKind: "postgres-read",
      processingStatus: "COMPLETED",
      extractionStatus: "COMPLETED",
      summaryStatus: "READY",
      confidenceBucket: "HIGH",
      bestScore: 0.91
    },
    {
      documentId: "doc-002",
      filename: "31_traceability.md",
      projectionSchemaVersion: "ae_document_detail_projection.v1",
      detailRoute: documentDetailRoute("doc-002"),
      ownerScope: localOwnerScope,
      sourceService: "nex-cx",
      sourceKind: "postgres-read",
      processingStatus: "COMPLETED",
      extractionStatus: "COMPLETED",
      summaryStatus: "READY",
      confidenceBucket: "HIGH",
      bestScore: 0.88
    },
    {
      documentId: "doc-003",
      filename: "36_sprint_backlog.md",
      projectionSchemaVersion: "ae_document_detail_projection.v1",
      detailRoute: documentDetailRoute("doc-003"),
      ownerScope: localOwnerScope,
      sourceService: "nex-cx",
      sourceKind: "postgres-read",
      processingStatus: "RUNNING",
      extractionStatus: "COMPLETED",
      summaryStatus: "READY",
      confidenceBucket: "MEDIUM",
      bestScore: 0.74
    }
  ],
  messages: [
    {
      role: "user",
      label: "사용자",
      text: "허용된 문서 범위에서 근거를 찾아 보고서를 작성해줘."
    },
    {
      role: "assistant",
      label: "assistant",
      text: "CX retrieval package와 structured draft 검증 결과를 기준으로 답변을 준비했습니다.",
      artifactRefs: []
    }
  ],
  progressEvents: buildProgressEvents(true),
  artifact: {
    handoffStatus: "READY",
    title: "MVP 착수 패키지 보고서",
    targetFormats: ["MD", "HTML_PREVIEW"],
    citationStatus: "VALIDATED",
    evidenceRefCount: 3,
    currentVersionId: "artifact-version-local-001",
    previewRoute: "/api/v1/artifact-files/artifact-file-local-001/preview",
    downloadRoutes: {
      MD: "/api/v1/artifact-files/artifact-file-local-001/download"
    }
  },
  audit: {
    resultStatus: "SUCCEEDED",
    sourceService: "nex-cx",
    compatibilityRuleId: "compat-grounded-answer-v1",
    providerAlias: "general-llm-default"
  }
};

workspaceState.messages[1].artifactRefs = [workspaceState.artifactRef];
workspaceState.documentDetailClient = createMockDocumentDetailClient({
  documents: workspaceState.documents
});

const serviceList = document.querySelector("#service-list");
const statusStrip = document.querySelector("#status-strip");
const refreshButton = document.querySelector("#refresh-button");
const composer = document.querySelector("#composer");
const promptInput = document.querySelector("#prompt");
const retrievalToggle = document.querySelector("#retrieval-toggle");
const formatSelect = document.querySelector("#format-select");
const messageList = document.querySelector("#message-list");
const documentList = document.querySelector("#document-list");
const documentDetail = document.querySelector("#document-detail");
const documentDetailStatus = document.querySelector("#document-detail-status");
const progressTimeline = document.querySelector("#progress-timeline");
const timelineCount = document.querySelector("#timeline-count");
const chatStatus = document.querySelector("#chat-status");
const workspaceId = document.querySelector("#workspace-id");
const documentCount = document.querySelector("#document-count");
const generationStage = document.querySelector("#generation-stage");
const artifactStatus = document.querySelector("#artifact-status");
const handoffBadge = document.querySelector("#handoff-badge");
const artifactSummary = document.querySelector("#artifact-summary");
const auditSummary = document.querySelector("#audit-summary");
let documentDetailRequestSequence = 0;

refreshButton.addEventListener("click", () => {
  renderServiceStatuses();
});

composer.addEventListener("submit", event => {
  event.preventDefault();
  appendPromptInteraction();
});

documentList.addEventListener("click", event => {
  const target = event.target.closest("[data-document-id]");
  if (!target) return;

  workspaceState.selectedDocumentId = target.dataset.documentId;
  renderDocuments();
  void renderDocumentDetail();
});

renderWorkspace();
renderServiceStatuses();

function renderWorkspace() {
  workspaceId.textContent = workspaceState.workspaceId;
  documentCount.textContent = `${workspaceState.documents.length}`;
  generationStage.textContent = statusLabel(workspaceState.progressEvents.at(-1)[2]);
  artifactStatus.textContent = statusLabel(workspaceState.artifact.handoffStatus);
  chatStatus.textContent = statusLabel(workspaceState.progressEvents.at(-1)[2]);
  chatStatus.className = `badge ${badgeClass(workspaceState.progressEvents.at(-1)[2])}`;
  handoffBadge.textContent = statusLabel(workspaceState.artifact.citationStatus);
  handoffBadge.className = `badge ${badgeClass(workspaceState.artifact.citationStatus)}`;
  renderMessages();
  renderDocuments();
  void renderDocumentDetail();
  renderTimeline();
  renderArtifactSummary();
  renderAuditSummary();
}

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

function renderMessages() {
  messageList.innerHTML = "";
  for (const message of workspaceState.messages) {
    const article = document.createElement("article");
    article.className = `message ${message.role}`;
    article.innerHTML = `
      <span>${escapeHtml(message.label)}</span>
      <p>${escapeHtml(message.text)}</p>
      ${renderArtifactRefs(message.artifactRefs || [])}
    `;
    messageList.appendChild(article);
  }
}

function renderArtifactRefs(artifactRefs) {
  if (!artifactRefs.length) return "";
  return `
    <div class="artifact-link-list" aria-label="연결된 아티팩트">
      ${artifactRefs.map(renderArtifactRef).join("")}
    </div>
  `;
}

function renderArtifactRef(artifactRef) {
  const downloadFormats = Object.keys(artifactRef.downloadRoutes || {});
  return `
    <div class="artifact-link" data-artifact-id="${escapeHtml(artifactRef.artifactId)}">
      <div class="artifact-link-heading">
        <strong>${escapeHtml(artifactRef.displayTitle)}</strong>
        <span class="badge ${badgeClass(artifactRef.artifactStatus)}">${statusLabel(artifactRef.artifactStatus)}</span>
      </div>
      <dl class="inline-meta slim">
        <div>
          <dt>version</dt>
          <dd>${escapeHtml(artifactRef.artifactVersionId)}</dd>
        </div>
        <div>
          <dt>source</dt>
          <dd>${escapeHtml(artifactRef.sourceGenerationId)}</dd>
        </div>
      </dl>
      <div class="artifact-actions">
        ${artifactRef.previewRoute ? `<a href="${escapeHtml(artifactRef.previewRoute)}">Preview</a>` : ""}
        ${downloadFormats.map(format => `<a href="${escapeHtml(artifactRef.downloadRoutes[format])}">${escapeHtml(format)}</a>`).join("")}
      </div>
    </div>
  `;
}

function renderDocuments() {
  documentList.innerHTML = "";
  for (const documentItem of workspaceState.documents) {
    const isSelected = documentItem.documentId === workspaceState.selectedDocumentId;
    const article = document.createElement("article");
    article.className = `document-row${isSelected ? " is-selected" : ""}`;
    article.innerHTML = `
      <div>
        <strong>${escapeHtml(documentItem.filename)}</strong>
        <span>${escapeHtml(documentItem.documentId)}</span>
      </div>
      <div class="document-action-row">
        <div class="badge-pair">
          <span class="badge ${badgeClass(documentItem.summaryStatus)}">${statusLabel(documentItem.summaryStatus)}</span>
          <span class="badge ${badgeClass(documentItem.confidenceBucket)}">${statusLabel(documentItem.confidenceBucket)}</span>
        </div>
        <button
          type="button"
          data-document-id="${escapeHtml(documentItem.documentId)}"
          aria-pressed="${isSelected ? "true" : "false"}"
        >상세</button>
      </div>
      <meter min="0" max="1" value="${documentItem.bestScore}"></meter>
    `;
    documentList.appendChild(article);
  }
}

async function renderDocumentDetail() {
  const documentItem = currentDocumentSurfaceItem();
  if (!documentItem) {
    documentDetailStatus.textContent = statusLabel("UNKNOWN");
    documentDetailStatus.className = `badge ${badgeClass("UNKNOWN")}`;
    documentDetail.innerHTML = "";
    return;
  }

  const requestSequence = ++documentDetailRequestSequence;
  documentDetailStatus.textContent = statusLabel("RUNNING");
  documentDetailStatus.className = `badge ${badgeClass("RUNNING")}`;
  documentDetail.classList.add("is-loading");

  let surface;
  try {
    surface = await workspaceState.documentDetailClient.getDocumentDetail(
      documentItem.documentId
    );
  } catch (error) {
    if (requestSequence !== documentDetailRequestSequence) return;
    renderDocumentDetailError(error);
    return;
  }

  if (requestSequence !== documentDetailRequestSequence) return;
  documentDetail.classList.remove("is-loading");
  documentDetailStatus.textContent = statusLabel(surface.processingStatus);
  documentDetailStatus.className = `badge ${badgeClass(surface.processingStatus)}`;
  documentDetail.innerHTML = `
    <strong>${escapeHtml(surface.filename)}</strong>
    <dl class="inline-meta">
      <div>
        <dt>route</dt>
        <dd><code>${escapeHtml(surface.detailRoute)}</code></dd>
      </div>
      <div>
        <dt>schema</dt>
        <dd>${escapeHtml(surface.projectionSchemaVersion)}</dd>
      </div>
      <div>
        <dt>owner</dt>
        <dd>${escapeHtml(surface.tenantId)} / ${escapeHtml(surface.ownerUserId)}</dd>
      </div>
      <div>
        <dt>source</dt>
        <dd>${escapeHtml(surface.sourceService)} · ${escapeHtml(surface.sourceKind)}</dd>
      </div>
      <div>
        <dt>client</dt>
        <dd>${escapeHtml(surface.clientMode)}</dd>
      </div>
      <div>
        <dt>extraction</dt>
        <dd>${statusLabel(surface.extractionStatus)}</dd>
      </div>
      <div>
        <dt>summary</dt>
        <dd>${statusLabel(surface.summaryStatus)} · ${statusLabel(surface.confidenceBucket)} · ${formatScore(surface.bestScore)}</dd>
      </div>
    </dl>
  `;
}

function renderDocumentDetailError(error) {
  documentDetail.classList.remove("is-loading");
  documentDetailStatus.textContent = statusLabel("UNAVAILABLE");
  documentDetailStatus.className = `badge ${badgeClass("UNAVAILABLE")}`;
  documentDetail.innerHTML = `
    <strong>문서 상세를 불러오지 못했습니다.</strong>
    <dl class="inline-meta">
      <div>
        <dt>status</dt>
        <dd>${escapeHtml(error.status || "DOCUMENT_DETAIL_CLIENT_ERROR")}</dd>
      </div>
      <div>
        <dt>retryable</dt>
        <dd>${escapeHtml(Boolean(error.retryable))}</dd>
      </div>
    </dl>
  `;
}

function currentDocumentSurfaceItem() {
  return (
    workspaceState.documents.find(
      documentItem => documentItem.documentId === workspaceState.selectedDocumentId
    ) || workspaceState.documents[0]
  );
}

function formatScore(score) {
  if (typeof score !== "number") return "n/a";
  return score.toFixed(2);
}

function renderTimeline() {
  progressTimeline.innerHTML = "";
  workspaceState.progressEvents.forEach((event, index) => {
    const [eventType, stage, status] = event;
    const item = document.createElement("li");
    item.className = status === "COMPLETED" ? "is-complete" : "is-running";
    item.innerHTML = `
      <span>${index + 1}</span>
      <div>
        <strong>${stage}</strong>
        <small>${eventType}</small>
      </div>
      <em>${statusLabel(status)}</em>
    `;
    progressTimeline.appendChild(item);
  });
  timelineCount.textContent = `${workspaceState.progressEvents.length} events`;
}

function renderArtifactSummary() {
  const downloadFormats = Object.keys(workspaceState.artifact.downloadRoutes || {});
  artifactSummary.innerHTML = `
    <strong>${escapeHtml(workspaceState.artifact.title)}</strong>
    <dl class="inline-meta">
      <div>
        <dt>handoff</dt>
        <dd>${escapeHtml(workspaceState.artifactHandoffId)}</dd>
      </div>
      <div>
        <dt>formats</dt>
        <dd>${workspaceState.artifact.targetFormats.map(escapeHtml).join(", ")}</dd>
      </div>
      <div>
        <dt>version</dt>
        <dd>${escapeHtml(workspaceState.artifact.currentVersionId)}</dd>
      </div>
      <div>
        <dt>citations</dt>
        <dd>${statusLabel(workspaceState.artifact.citationStatus)} · ${workspaceState.artifact.evidenceRefCount}</dd>
      </div>
      <div>
        <dt>preview</dt>
        <dd>${escapeHtml(workspaceState.artifact.previewRoute)}</dd>
      </div>
      <div>
        <dt>download</dt>
        <dd>${downloadFormats.map(format => `${format}: ${workspaceState.artifact.downloadRoutes[format]}`).map(escapeHtml).join(", ")}</dd>
      </div>
    </dl>
  `;
}

function renderAuditSummary() {
  auditSummary.innerHTML = `
    <div>
      <dt>결과</dt>
      <dd>${escapeHtml(workspaceState.audit.resultStatus)}</dd>
    </div>
    <div>
      <dt>소스</dt>
      <dd>${escapeHtml(workspaceState.audit.sourceService)}</dd>
    </div>
    <div>
      <dt>규칙</dt>
      <dd>${escapeHtml(workspaceState.audit.compatibilityRuleId)}</dd>
    </div>
    <div>
      <dt>모델</dt>
      <dd>${escapeHtml(workspaceState.audit.providerAlias)}</dd>
    </div>
  `;
}

function appendPromptInteraction() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    promptInput.focus();
    return;
  }

  const format = formatSelect.value;
  const grounded = retrievalToggle.checked;
  workspaceState.messages.push({
    role: "user",
    label: "사용자",
    text: prompt
  });
  workspaceState.messages.push({
    role: "assistant",
    label: "assistant",
    text: grounded
      ? `근거 패키지와 ${format} handoff를 연결했습니다.`
      : `${format} 생성 요청을 일반 답변 흐름으로 연결했습니다.`,
    artifactRefs: [buildMockArtifactRef(format, grounded)]
  });
  workspaceState.artifact.targetFormats = [format];
  workspaceState.artifact.handoffStatus = "READY";
  workspaceState.artifact.citationStatus = grounded ? "VALIDATED" : "NOT_REQUIRED";
  workspaceState.artifact.currentVersionId = workspaceState.artifactRef.artifactVersionId;
  workspaceState.artifact.previewRoute = workspaceState.artifactRef.previewRoute;
  workspaceState.artifact.downloadRoutes = workspaceState.artifactRef.downloadRoutes;
  workspaceState.progressEvents = buildProgressEvents(grounded);
  renderWorkspace();
}

function buildMockArtifactRef(format, grounded) {
  const artifactFileId = `artifact-file-local-${format.toLowerCase()}`;
  const artifactRef = {
    ...workspaceState.artifactRef,
    artifactStatus: "READY",
    primaryFormat: format,
    availableFormats: [format],
    previewRoute: `/api/v1/artifact-files/${artifactFileId}/preview`,
    downloadRoutes: {
      [format]: `/api/v1/artifact-files/${artifactFileId}/download`
    },
    qualitySummary: {
      ...workspaceState.artifactRef.qualitySummary,
      citationStatus: grounded ? "VALIDATED" : "NOT_REQUIRED",
      groundingRequired: grounded
    }
  };
  workspaceState.artifactRef = artifactRef;
  return artifactRef;
}

function buildProgressEvents(grounded) {
  if (grounded) return [...baseProgressEvents];
  return baseProgressEvents.filter(event => event[0] !== "generation.retrieval.ready");
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
  if (["HEALTHY", "READY", "VALIDATED", "SUCCEEDED", "HIGH"].includes(status)) {
    return "success";
  }
  if (["DEGRADED", "LOW_CONFIDENCE", "MEDIUM", "PREVIEW_ONLY"].includes(status)) {
    return "warning";
  }
  if (["RUNNING", "READY_FOR_RENDERING"].includes(status)) return "running";
  if (["PENDING", "UNKNOWN", "NOT_REQUIRED"].includes(status)) return "pending";
  return "danger";
}

function statusLabel(status) {
  const labels = {
    COMPLETED: "완료",
    RUNNING: "진행",
    READY: "준비",
    READY_FOR_RENDERING: "렌더링 준비",
    PREVIEW_ONLY: "미리보기",
    VALIDATED: "검증됨",
    SUCCEEDED: "성공",
    NOT_REQUIRED: "불필요",
    NOT_READY: "미준비",
    UNHEALTHY: "비정상",
    UNAVAILABLE: "사용 불가",
    HIGH: "높음",
    MEDIUM: "중간"
  };
  return labels[status] || status;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
