import {
  buildAuthenticatedRuntimeSummary
} from "./authenticatedRuntime.js";
import {
  bootstrapAuthenticatedSessionRuntime,
  buildSessionBootstrapSummary,
  composeAuthenticatedSessionRuntime
} from "./sessionBootstrap.js";
import {
  buildClientRegistrySummary
} from "./clientRegistry.js";
import {
  buildCredentialLoginRequestFromForm,
  buildCredentialLoginSurfaceSummary,
  createCredentialLoginSurfaceState
} from "./credentialLoginSurface.js";
import {
  documentDetailRoute
} from "./documentDetailClient.js";
import {
  buildDocumentScope,
  buildRetrievalRequest,
  documentScopeLabel
} from "./documentScope.js";
import {
  buildRuntimeConfigSummary,
  loadRuntimeConfig
} from "./runtimeConfig.js";
import {
  buildRuntimeDiagnostics,
  buildRuntimeDiagnosticsSummary
} from "./runtimeDiagnostics.js";
import {
  buildSessionRouteGuard,
  buildSessionRouteGuardSummary,
  ownerScopeFromSessionState
} from "./sessionRouteGuard.js";
import {
  buildOperationStateSummary,
  createOperationState,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "./operationState.js";
import {
  buildOperationFeedback
} from "./operationFeedback.js";
import {
  buildRetrievalQualityWarningSurface,
  buildRetrievalQualityWarningSummary
} from "./retrievalQualityWarnings.js";
import {
  buildGroundedResponseQualitySurface,
  buildGroundedResponseQualitySummary
} from "./groundedResponseQuality.js";
import {
  buildGenerationFeedbackRequest,
  buildGenerationFeedbackSurfaceSummary,
  createGenerationFeedbackSurfaceState
} from "./generationFeedback.js";
import {
  buildRepairedResponseReviewSurfaceFromProjection
} from "./repairedResponseReviewClient.js";
import {
  renderRepairedResponseReviewCard
} from "./repairedResponseReviewCard.js";
import {
  buildUploadFileMetadata,
  buildUploadHandoffPayload,
  buildUploadSurfaceDraftFromFileMetadata
} from "./uploadSurface.js";

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
  ownerUserId: "owner-local",
  uploadedByUserId: "owner-local"
};

const defaultUploadFileMetadata = buildUploadFileMetadata({
  filename: "new-reference-pack.md",
  contentType: "text/markdown",
  sizeBytes: 4096,
  sourceSha256: "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610"
});

const workspaceState = {
  workspaceId: "workspace-local",
  chatDocumentId: "chat-doc-local",
  interactionId: "interaction-local",
  cxGenerationId: "cx-gen-local",
  retrievalPackageId: "cx-ret-local",
  artifactHandoffId: "handoff-local",
  selectedDocumentId: "doc-001",
  sessionBootstrap: null,
  authenticatedRuntime: null,
  runtimeConfig: null,
  sessionState: null,
  sessionClient: null,
  sessionRouteGuard: null,
  credentialLogin: createCredentialLoginSurfaceState({
    tenantId: localOwnerScope.tenantId,
    requestedScopes: ["workspace:use", "documents:upload"]
  }),
  authBoundary: null,
  clientRegistry: null,
  operations: null,
  documentScope: null,
  lastRetrievalRequest: null,
  lastRetrievalResult: null,
  generationFeedbackClient: null,
  uploadSubmission: null,
  uploadFileMetadata: defaultUploadFileMetadata,
  uploadDraft: buildUploadSurfaceDraftFromFileMetadata({
    workspaceId: "workspace-local",
    fileMetadata: defaultUploadFileMetadata,
    ownerScope: localOwnerScope
  }),
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
      artifactRefs: [],
      groundedResponseQuality: buildGroundedResponseQualitySurface({
        generation: {
          grounded_response_quality: buildMockGroundedResponseQualityContract(true)
        }
      }),
      generationFeedback: createGenerationFeedbackSurfaceState({
        interactionId: "interaction-local",
        chatDocumentId: "chat-doc-local",
        cxGenerationId: "cx-gen-local"
      }),
      repairedResponseReview: buildRepairedResponseReviewSurfaceFromProjection(
        buildMockRepairedResponseReviewProjection()
      )
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
workspaceState.sessionBootstrap = composeAuthenticatedSessionRuntime({
  runtimeConfig: loadRuntimeConfig(),
  documents: workspaceState.documents
});
applySessionBootstrap(workspaceState.sessionBootstrap);
workspaceState.documentScope = buildCurrentDocumentScope();
workspaceState.operations = initializeOperationStates();

const serviceList = document.querySelector("#service-list");
const statusStrip = document.querySelector("#status-strip");
const refreshButton = document.querySelector("#refresh-button");
const runtimeDiagnosticsStatus = document.querySelector("#runtime-diagnostics-status");
const runtimeDiagnosticsSummary = document.querySelector("#runtime-diagnostics-summary");
const runtimeDiagnosticsPreview = document.querySelector("#runtime-diagnostics-preview");
const credentialLoginForm = document.querySelector("#credential-login-form");
const credentialTenantInput = document.querySelector("#credential-tenant-id");
const credentialEmployeeInput = document.querySelector("#credential-employee-id");
const credentialPasswordInput = document.querySelector("#credential-password");
const credentialLoginStatus = document.querySelector("#credential-login-status");
const credentialLoginFeedback = document.querySelector("#credential-login-feedback");
const credentialLoginSummary = document.querySelector("#credential-login-summary");
const sessionRouteGuardSummary = document.querySelector("#session-route-guard-summary");
const credentialLoginSubmitButton = document.querySelector("#credential-login-submit-button");
const credentialLogoutButton = document.querySelector("#credential-logout-button");
const composer = document.querySelector("#composer");
const promptInput = document.querySelector("#prompt");
const retrievalToggle = document.querySelector("#retrieval-toggle");
const formatSelect = document.querySelector("#format-select");
const messageList = document.querySelector("#message-list");
const documentList = document.querySelector("#document-list");
const documentDetail = document.querySelector("#document-detail");
const documentDetailStatus = document.querySelector("#document-detail-status");
const documentDetailFeedback = document.querySelector("#document-detail-feedback");
const documentDetailRetryButton = document.querySelector("#document-detail-retry-button");
const uploadMetadataForm = document.querySelector("#upload-metadata-form");
const uploadFileInput = document.querySelector("#upload-file-input");
const uploadSourceSha256Input = document.querySelector("#upload-source-sha256");
const uploadStatus = document.querySelector("#upload-status");
const uploadSubmitButton = document.querySelector("#upload-submit-button");
const uploadRetryButton = document.querySelector("#upload-retry-button");
const uploadFeedback = document.querySelector("#upload-feedback");
const uploadFileMetadataSummary = document.querySelector("#upload-file-metadata-summary");
const uploadOwnerScope = document.querySelector("#upload-owner-scope");
const uploadClientSummary = document.querySelector("#upload-client-summary");
const uploadPayloadPreview = document.querySelector("#upload-payload-preview");
const retrievalScopeStatus = document.querySelector("#retrieval-scope-status");
const retrievalFeedback = document.querySelector("#retrieval-feedback");
const retrievalQualityWarnings = document.querySelector("#retrieval-quality-warnings");
const groundedResponseQuality = document.querySelector("#grounded-response-quality");
const retrievalRetryButton = document.querySelector("#retrieval-retry-button");
const retrievalScopeSummary = document.querySelector("#retrieval-scope-summary");
const retrievalClientSummary = document.querySelector("#retrieval-client-summary");
const retrievalScopePreview = document.querySelector("#retrieval-scope-preview");
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

credentialLoginForm.addEventListener("submit", event => {
  event.preventDefault();
  void submitCredentialLogin();
});

credentialLogoutButton.addEventListener("click", () => {
  void logoutCredentialSession();
});

composer.addEventListener("submit", event => {
  event.preventDefault();
  void appendPromptInteraction();
});

uploadSubmitButton.addEventListener("click", () => {
  void submitUploadDraft();
});

uploadRetryButton.addEventListener("click", () => {
  void submitUploadDraft();
});

documentDetailRetryButton.addEventListener("click", () => {
  void renderDocumentDetail();
});

retrievalRetryButton.addEventListener("click", () => {
  void retryLastRetrievalRequest();
});

messageList.addEventListener("click", event => {
  const target = event.target.closest("[data-generation-feedback-value]");
  if (!target) return;
  const interactionId = target.closest("[data-interaction-id]")?.dataset.interactionId;
  if (!interactionId) return;
  void submitGenerationFeedback(interactionId, target.dataset.generationFeedbackValue);
});

uploadMetadataForm.addEventListener("submit", event => {
  event.preventDefault();
  applyUploadFileMetadataFromForm();
});

uploadFileInput.addEventListener("change", () => {
  applyUploadFileMetadataFromForm();
});

documentList.addEventListener("click", event => {
  const target = event.target.closest("[data-document-id]");
  if (!target) return;

  workspaceState.selectedDocumentId = target.dataset.documentId;
  workspaceState.documentScope = buildCurrentDocumentScope();
  renderDocuments();
  renderRetrievalScope();
  renderGroundedResponseQualitySurface(
    groundedResponseQuality,
    currentGroundedResponseQualitySurface()
  );
  void renderDocumentDetail();
});

renderWorkspace();
renderServiceStatuses();
void refreshBrowserSessionRuntime();

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
  renderCredentialLoginSurface();
  renderUploadSurface();
  renderDocuments();
  renderRetrievalScope();
  void renderDocumentDetail();
  renderTimeline();
  renderArtifactSummary();
  renderAuditSummary();
  renderRuntimeDiagnostics();
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

function applySessionBootstrap(sessionBootstrap) {
  workspaceState.sessionBootstrap = sessionBootstrap;
  workspaceState.authenticatedRuntime = sessionBootstrap.runtime;
  workspaceState.runtimeConfig = workspaceState.authenticatedRuntime.runtimeConfig;
  workspaceState.sessionState = workspaceState.authenticatedRuntime.sessionState;
  workspaceState.sessionClient = workspaceState.authenticatedRuntime.sessionClient;
  workspaceState.authBoundary = workspaceState.authenticatedRuntime.authBoundary;
  workspaceState.clientRegistry = workspaceState.authenticatedRuntime.clientRegistry;
  workspaceState.sessionRouteGuard = buildSessionRouteGuard({
    sessionState: workspaceState.sessionState,
    authBoundary: workspaceState.authBoundary,
    clientRegistry: workspaceState.clientRegistry
  });
  syncOwnerScopeFromSessionClaims();
  workspaceState.documentDetailClient = workspaceState.clientRegistry.documentDetailClient;
  workspaceState.uploadClient = workspaceState.clientRegistry.uploadClient;
  workspaceState.retrievalClient = workspaceState.clientRegistry.retrievalClient;
  workspaceState.generationFeedbackClient =
    workspaceState.clientRegistry.generationFeedbackClient;
  workspaceState.repairedResponseReviewClient =
    workspaceState.clientRegistry.repairedResponseReviewClient;
}

function syncOwnerScopeFromSessionClaims() {
  const ownerScope = ownerScopeFromSessionState(workspaceState.sessionState);
  if (!ownerScope) return;
  workspaceState.documents = workspaceState.documents.map(documentItem => ({
    ...documentItem,
    ownerScope: {
      tenantId: ownerScope.tenantId,
      ownerUserId: ownerScope.ownerUserId,
      uploadedByUserId: ownerScope.uploadedByUserId
    }
  }));
  workspaceState.uploadDraft = buildUploadSurfaceDraftFromFileMetadata({
    workspaceId: workspaceState.uploadDraft.workspaceId,
    fileMetadata: workspaceState.uploadFileMetadata,
    ownerScope
  });
  workspaceState.documentScope = buildCurrentDocumentScope();
}

async function refreshBrowserSessionRuntime() {
  const nextBootstrap = await bootstrapAuthenticatedSessionRuntime({
    runtimeConfig: workspaceState.runtimeConfig,
    sessionClient: workspaceState.sessionClient,
    documents: workspaceState.documents
  });
  applySessionBootstrap(nextBootstrap);
  workspaceState.operations = initializeOperationStates();
  renderRuntimeDiagnostics();
  renderCredentialLoginSurface();
  renderUploadSurface();
  renderRetrievalScope();
}

async function submitCredentialLogin() {
  credentialLoginSubmitButton.disabled = true;
  credentialLogoutButton.disabled = true;
  workspaceState.credentialLogin = createCredentialLoginSurfaceState({
    tenantId: credentialTenantInput.value,
    employeeId: credentialEmployeeInput.value,
    requestedScopes: ["workspace:use", "documents:upload"],
    status: "SUBMITTING",
    reason: "login_requested"
  });
  renderCredentialLoginSurface();

  try {
    const loginRequest = buildCredentialLoginRequestFromForm({
      tenantInput: credentialTenantInput,
      employeeInput: credentialEmployeeInput,
      passwordInput: credentialPasswordInput,
      requestedScopes: ["workspace:use", "documents:upload"]
    });
    credentialPasswordInput.value = "";
    const sessionState = await workspaceState.sessionClient.login(loginRequest);
    workspaceState.credentialLogin = createCredentialLoginSurfaceState({
      tenantId: loginRequest.tenant_id,
      employeeId: loginRequest.employee_id,
      requestedScopes: loginRequest.requested_scopes,
      ttlSeconds: loginRequest.ttl_seconds,
      status: "AUTHENTICATED",
      reason: "login_succeeded"
    });
    const nextBootstrap = composeAuthenticatedSessionRuntime({
      runtimeConfig: workspaceState.runtimeConfig,
      sessionState,
      sessionClient: workspaceState.sessionClient,
      documents: workspaceState.documents
    });
    applySessionBootstrap(nextBootstrap);
    workspaceState.operations = initializeOperationStates();
    renderWorkspace();
  } catch (error) {
    credentialPasswordInput.value = "";
    workspaceState.credentialLogin = createCredentialLoginSurfaceState({
      tenantId: credentialTenantInput.value,
      employeeId: credentialEmployeeInput.value,
      requestedScopes: ["workspace:use", "documents:upload"],
      status: "FAILED",
      reason: "login_failed",
      errorStatus: error.status || "CREDENTIAL_LOGIN_FAILED"
    });
    renderCredentialLoginSurface();
    renderRuntimeDiagnostics();
  } finally {
    credentialLoginSubmitButton.disabled = false;
    credentialLogoutButton.disabled =
      workspaceState.sessionState?.status !== "authenticated";
  }
}

async function logoutCredentialSession() {
  credentialLogoutButton.disabled = true;
  try {
    const sessionState = await workspaceState.sessionClient.logout();
    workspaceState.credentialLogin = createCredentialLoginSurfaceState({
      tenantId: credentialTenantInput.value,
      employeeId: credentialEmployeeInput.value,
      requestedScopes: ["workspace:use", "documents:upload"],
      status: "LOGGED_OUT",
      reason: "logout"
    });
    const nextBootstrap = composeAuthenticatedSessionRuntime({
      runtimeConfig: workspaceState.runtimeConfig,
      sessionState,
      sessionClient: workspaceState.sessionClient,
      documents: workspaceState.documents
    });
    applySessionBootstrap(nextBootstrap);
    workspaceState.operations = initializeOperationStates();
    renderWorkspace();
  } catch (error) {
    workspaceState.credentialLogin = createCredentialLoginSurfaceState({
      tenantId: credentialTenantInput.value,
      employeeId: credentialEmployeeInput.value,
      requestedScopes: ["workspace:use", "documents:upload"],
      status: "FAILED",
      reason: "logout_failed",
      errorStatus: error.status || "CREDENTIAL_LOGOUT_FAILED"
    });
    renderCredentialLoginSurface();
    renderRuntimeDiagnostics();
  } finally {
    credentialLogoutButton.disabled =
      workspaceState.sessionState?.status !== "authenticated";
  }
}

function renderCredentialLoginSurface() {
  const summary = buildCredentialLoginSurfaceSummary(workspaceState.credentialLogin);
  const guard = buildSessionRouteGuardSummary(workspaceState.sessionRouteGuard);
  credentialLoginStatus.textContent = statusLabel(summary.status);
  credentialLoginStatus.className = `badge ${badgeClass(summary.status)}`;
  credentialTenantInput.value = workspaceState.credentialLogin.tenantId;
  credentialEmployeeInput.value = workspaceState.credentialLogin.employeeId;
  credentialLogoutButton.hidden = workspaceState.sessionState?.status !== "authenticated";
  credentialLogoutButton.disabled = workspaceState.sessionState?.status !== "authenticated";
  credentialLoginFeedback.dataset.severity =
    summary.status === "FAILED"
      ? "danger"
      : summary.status === "AUTHENTICATED"
        ? "success"
        : summary.status === "SUBMITTING"
          ? "running"
          : "idle";
  credentialLoginFeedback.textContent = credentialLoginFeedbackMessage(summary);
  credentialLoginSummary.innerHTML = `
    <div>
      <dt>tenant</dt>
      <dd>${escapeHtml(summary.tenant_id)}</dd>
    </div>
    <div>
      <dt>employee</dt>
      <dd>${escapeHtml(summary.employee_id_present ? "present" : "empty")}</dd>
    </div>
    <div>
      <dt>session</dt>
      <dd>${escapeHtml(workspaceState.sessionState.status)} · ${escapeHtml(workspaceState.sessionBootstrap.phase)}</dd>
    </div>
    <div>
      <dt>scopes</dt>
      <dd>${escapeHtml(summary.requested_scope_count)}</dd>
    </div>
    <div>
      <dt>metadata</dt>
      <dd>${escapeHtml(summary.metadata.rawPasswordStored)} · ${escapeHtml(summary.metadata.passwordIncludedInSummary)}</dd>
    </div>
  `;
  sessionRouteGuardSummary.innerHTML = `
    <div>
      <dt>guard</dt>
      <dd>${escapeHtml(guard.guard_status)}</dd>
    </div>
    <div>
      <dt>mode</dt>
      <dd>${escapeHtml(guard.client_mode)}</dd>
    </div>
    <div>
      <dt>owner</dt>
      <dd>${escapeHtml(guard.owner_scope_source)}</dd>
    </div>
    <div>
      <dt>routes</dt>
      <dd>${escapeHtml(guard.allowed_route_count)} / ${escapeHtml(guard.protected_route_count)}</dd>
    </div>
    <div>
      <dt>blocked</dt>
      <dd>${escapeHtml(guard.blocked_reasons.join(", ") || "none")}</dd>
    </div>
  `;
}

function credentialLoginFeedbackMessage(summary) {
  if (summary.status === "AUTHENTICATED") {
    return "로그인 세션이 활성화되었습니다.";
  }
  if (summary.status === "SUBMITTING") {
    return "로그인 요청을 처리하고 있습니다.";
  }
  if (summary.status === "FAILED") {
    return `로그인을 완료하지 못했습니다. ${summary.error_status || "LOGIN_FAILED"}`;
  }
  if (summary.status === "LOGGED_OUT") {
    return "로그아웃되었습니다.";
  }
  return "로그인 준비가 완료되었습니다.";
}

function buildCurrentDocumentScope() {
  return buildDocumentScope({
    documents: workspaceState.documents,
    selectedDocumentIds: [workspaceState.selectedDocumentId]
  });
}

function initializeOperationStates() {
  return {
    documentDetail: createOperationState({
      operationId: "document_detail",
      label: "Document detail",
      status: "READY",
      clientMode: workspaceState.documentDetailClient.clientMode,
      route: documentDetailRoute(workspaceState.selectedDocumentId)
    }),
    upload: createOperationState({
      operationId: "upload_handoff",
      label: "Upload handoff",
      status: "READY_FOR_SUBMIT",
      clientMode: workspaceState.uploadClient.clientMode,
      route: workspaceState.uploadDraft.uploadRoute
    }),
    retrieval: createOperationState({
      operationId: "retrieval_context",
      label: "Retrieval context",
      status: "READY_FOR_PROMPT",
      clientMode: workspaceState.retrievalClient.clientMode,
      route: workspaceState.documentScope.route
    }),
    generationFeedback: createOperationState({
      operationId: "generation_feedback",
      label: "Generation feedback",
      status: "READY",
      clientMode: workspaceState.generationFeedbackClient.clientMode,
      route: "/api/v1/chat/interactions/{interaction_id}/feedback"
    })
  };
}

function applyUploadFileMetadataFromForm() {
  const ownerScope =
    ownerScopeFromSessionState(workspaceState.sessionState) ||
    workspaceState.uploadDraft.ownerScope;
  const selectedFile = uploadFileInput.files?.[0] || null;

  try {
    const fileMetadata = buildUploadFileMetadata({
      file: selectedFile || undefined,
      filename: selectedFile?.name || workspaceState.uploadFileMetadata.filename,
      contentType:
        selectedFile?.type ||
        workspaceState.uploadFileMetadata.contentType ||
        "application/octet-stream",
      sizeBytes: selectedFile?.size ?? workspaceState.uploadFileMetadata.sizeBytes,
      sourceSha256: uploadSourceSha256Input.value.trim() || null
    });
    workspaceState.uploadFileMetadata = fileMetadata;
    workspaceState.uploadDraft = buildUploadSurfaceDraftFromFileMetadata({
      workspaceId: workspaceState.workspaceId,
      fileMetadata,
      ownerScope
    });
    workspaceState.uploadSubmission = null;
    workspaceState.operations.upload = createOperationState({
      operationId: "upload_handoff",
      label: "Upload handoff",
      status: "READY_FOR_SUBMIT",
      clientMode: workspaceState.uploadClient.clientMode,
      route: workspaceState.uploadDraft.uploadRoute
    });
  } catch (error) {
    workspaceState.operations.upload = markOperationFailed(
      workspaceState.operations.upload,
      {
        error,
        clientMode: workspaceState.uploadClient.clientMode,
        route: workspaceState.uploadDraft.uploadRoute
      }
    );
  }

  renderUploadSurface();
}

function renderUploadSurface() {
  const draft = workspaceState.uploadDraft;
  const fileMetadata = workspaceState.uploadFileMetadata;
  const payload = buildUploadHandoffPayload(draft);
  const submission = workspaceState.uploadSubmission;
  const operation = workspaceState.operations.upload;
  const uploadState = operation.status || submission?.status || draft.status;
  uploadStatus.textContent = statusLabel(uploadState);
  uploadStatus.className = `badge ${badgeClass(uploadState)}`;
  renderOperationFeedback(uploadFeedback, uploadRetryButton, operation, {
    operationLabel: "업로드 전송",
    idleMessage: "업로드 전송 준비가 완료되었습니다.",
    runningMessage: "업로드 handoff를 전송하고 있습니다.",
    succeededMessage: "업로드 handoff가 접수되었습니다.",
    failedMessage: "업로드 handoff를 완료하지 못했습니다."
  });
  renderRuntimeDiagnostics();
  uploadSourceSha256Input.value = draft.sourceSha256 || "";
  uploadFileMetadataSummary.innerHTML = `
    <div>
      <dt>file</dt>
      <dd>${escapeHtml(fileMetadata.filename)}</dd>
    </div>
    <div>
      <dt>type</dt>
      <dd>${escapeHtml(fileMetadata.contentType)}</dd>
    </div>
    <div>
      <dt>size</dt>
      <dd>${escapeHtml(fileMetadata.sizeBytes)} bytes</dd>
    </div>
    <div>
      <dt>hash</dt>
      <dd>${escapeHtml(fileMetadata.sourceSha256 ? "present" : "empty")}</dd>
    </div>
  `;
  uploadOwnerScope.innerHTML = `
    <div>
      <dt>tenant</dt>
      <dd>${escapeHtml(draft.ownerScope.tenantId)}</dd>
    </div>
    <div>
      <dt>owner</dt>
      <dd>${escapeHtml(draft.ownerScope.ownerUserId)}</dd>
    </div>
    <div>
      <dt>uploaded_by</dt>
      <dd>${escapeHtml(draft.ownerScope.uploadedByUserId)}</dd>
    </div>
    <div>
      <dt>route</dt>
      <dd><code>${escapeHtml(draft.uploadRoute)}</code></dd>
    </div>
    <div>
      <dt>source</dt>
      <dd>${escapeHtml(draft.filename)} · ${escapeHtml(draft.contentType)} · ${escapeHtml(draft.sizeBytes)} bytes</dd>
    </div>
  `;
  uploadClientSummary.innerHTML = renderUploadClientSummary(submission);
  uploadPayloadPreview.textContent = JSON.stringify(
    safeUploadPreview(payload, draft, submission),
    null,
    2
  );
}

function renderUploadClientSummary(submission) {
  const operation = buildOperationStateSummary(workspaceState.operations.upload);
  if (!submission) {
    return `
      <div>
        <dt>client</dt>
        <dd>${escapeHtml(workspaceState.uploadClient.clientMode)}</dd>
      </div>
      <div>
        <dt>operation</dt>
        <dd>${escapeHtml(operation.phase)} · ${escapeHtml(operation.status)} · attempt ${escapeHtml(operation.attempt)}</dd>
      </div>
    `;
  }

  return `
    <div>
      <dt>client</dt>
      <dd>${escapeHtml(submission.clientMode || workspaceState.uploadClient.clientMode)}</dd>
    </div>
    <div>
      <dt>operation</dt>
      <dd>${escapeHtml(operation.phase)} · ${escapeHtml(operation.status)} · attempt ${escapeHtml(operation.attempt)}</dd>
    </div>
    <div>
      <dt>handoff</dt>
      <dd>${escapeHtml(submission.uploadHandoffId || "n/a")}</dd>
    </div>
    <div>
      <dt>document</dt>
      <dd>${escapeHtml(submission.documentId || "n/a")}</dd>
    </div>
  `;
}

function renderRetrievalScope() {
  const scope = workspaceState.documentScope;
  const retrievalResult = workspaceState.lastRetrievalResult;
  const operation = workspaceState.operations.retrieval;
  retrievalScopeStatus.textContent = statusLabel(
    operation.status || retrievalResult?.status || (scope.selectedCount > 0 ? "READY" : "UNKNOWN")
  );
  retrievalScopeStatus.className = `badge ${badgeClass(
    operation.status || retrievalResult?.status || (scope.selectedCount > 0 ? "READY" : "UNKNOWN")
  )}`;
  renderOperationFeedback(retrievalFeedback, retrievalRetryButton, operation, {
    operationLabel: "검색 요청",
    idleMessage: "검색 요청 준비가 완료되었습니다.",
    runningMessage: "선택 문서 범위로 검색 요청을 처리하고 있습니다.",
    succeededMessage: "검색 컨텍스트가 준비되었습니다.",
    failedMessage: "검색 요청을 완료하지 못했습니다."
  });
  renderRetrievalQualityWarningSurface(retrievalQualityWarnings, retrievalResult);
  renderRuntimeDiagnostics();
  retrievalScopeSummary.innerHTML = `
    <div>
      <dt>route</dt>
      <dd><code>${escapeHtml(scope.route)}</code></dd>
    </div>
    <div>
      <dt>documents</dt>
      <dd>${escapeHtml(documentScopeLabel(scope))}</dd>
    </div>
    <div>
      <dt>scope ids</dt>
      <dd>${escapeHtml(scope.document_scope.document_ids.join(", "))}</dd>
    </div>
  `;
  retrievalClientSummary.innerHTML = renderRetrievalClientSummary(retrievalResult);
  retrievalScopePreview.textContent = JSON.stringify(
    safeRetrievalPreview(workspaceState.lastRetrievalRequest, scope, retrievalResult),
    null,
    2
  );
}

function renderRetrievalClientSummary(retrievalResult) {
  const operation = buildOperationStateSummary(workspaceState.operations.retrieval);
  if (!retrievalResult) {
    return `
      <div>
        <dt>client</dt>
        <dd>${escapeHtml(workspaceState.retrievalClient.clientMode)}</dd>
      </div>
      <div>
        <dt>operation</dt>
        <dd>${escapeHtml(operation.phase)} · ${escapeHtml(operation.status)} · attempt ${escapeHtml(operation.attempt)}</dd>
      </div>
    `;
  }

  return `
    <div>
      <dt>client</dt>
      <dd>${escapeHtml(retrievalResult.clientMode || workspaceState.retrievalClient.clientMode)}</dd>
    </div>
    <div>
      <dt>operation</dt>
      <dd>${escapeHtml(operation.phase)} · ${escapeHtml(operation.status)} · attempt ${escapeHtml(operation.attempt)}</dd>
    </div>
    <div>
      <dt>package</dt>
      <dd>${escapeHtml(retrievalResult.cxRetrievalPackageId || "n/a")}</dd>
    </div>
    <div>
      <dt>evidence</dt>
      <dd>${escapeHtml(retrievalResult.evidenceCount ?? 0)} · ${escapeHtml(retrievalResult.confidenceBucket || "UNKNOWN")}</dd>
    </div>
  `;
}

function renderMessages() {
  messageList.innerHTML = "";
  for (const message of workspaceState.messages) {
    const article = document.createElement("article");
    article.className = `message ${message.role}`;
    if (message.generationFeedback) {
      article.dataset.interactionId = message.generationFeedback.interaction_id;
    }
    article.innerHTML = `
      <span>${escapeHtml(message.label)}</span>
      <p>${escapeHtml(message.text)}</p>
      ${renderMessageRetrievalScope(message.retrievalScope)}
      ${renderMessageRetrievalQualityWarning(message.retrievalQualityWarning)}
      ${renderMessageGroundedResponseQuality(message.groundedResponseQuality)}
      ${renderArtifactRefs(message.artifactRefs || [])}
      ${renderMessageRepairedResponseReview(message.repairedResponseReview)}
      ${renderMessageGenerationFeedback(message.generationFeedback)}
    `;
    messageList.appendChild(article);
  }
}

function renderRetrievalQualityWarningSurface(container, source) {
  const surface = buildRetrievalQualityWarningSurface(source || {});
  container.hidden = !surface.visible;
  container.dataset.severity = surface.severity;
  container.dataset.action = surface.recommended_action;
  container.innerHTML = surface.visible ? renderRetrievalQualityWarning(surface) : "";
}

function renderMessageRetrievalScope(retrievalScope) {
  if (!retrievalScope) return "";
  return `
    <dl class="inline-meta slim retrieval-scope-chip" aria-label="검색 범위">
      <div>
        <dt>scope</dt>
        <dd>${escapeHtml(documentScopeLabel(retrievalScope))}</dd>
      </div>
    </dl>
  `;
}

function renderMessageRetrievalQualityWarning(surface) {
  if (!surface?.visible) return "";
  return renderRetrievalQualityWarning(surface, {
    className: "inline-meta slim retrieval-quality-warning-chip"
  });
}

function renderMessageGroundedResponseQuality(surface) {
  if (!surface?.visible) return "";
  return renderGroundedResponseQuality(surface, {
    className: "inline-meta slim grounded-response-quality-chip"
  });
}

function renderMessageGenerationFeedback(surface) {
  if (!surface) return "";
  const summary = buildGenerationFeedbackSurfaceSummary(surface);
  const disabled = summary.status === "SUBMITTING" ? "disabled" : "";
  return `
    <div
      class="generation-feedback-surface"
      data-status="${escapeHtml(summary.status)}"
      aria-label="생성 응답 피드백"
    >
      <div class="generation-feedback-actions">
        ${renderGenerationFeedbackButton(summary, "positive", "좋아요", disabled)}
        ${renderGenerationFeedbackButton(summary, "negative", "문제", disabled)}
        ${renderGenerationFeedbackButton(summary, "neutral", "보통", disabled)}
      </div>
      <dl class="inline-meta slim generation-feedback-summary">
        <div>
          <dt>status</dt>
          <dd>${escapeHtml(summary.status)}</dd>
        </div>
        <div>
          <dt>feedback</dt>
          <dd>${escapeHtml(summary.feedback_value)} · ${escapeHtml(summary.selected_reason_count)}</dd>
        </div>
        <div>
          <dt>route</dt>
          <dd>${escapeHtml(summary.route)}</dd>
        </div>
      </dl>
    </div>
  `;
}

function renderMessageRepairedResponseReview(surface) {
  if (!surface) return "";
  return renderRepairedResponseReviewCard(surface, {
    decisionEnabled: false
  });
}

function renderGenerationFeedbackButton(summary, value, label, disabled) {
  return `
    <button
      type="button"
      data-generation-feedback-value="${escapeHtml(value)}"
      aria-pressed="${summary.feedback_value === value ? "true" : "false"}"
      ${disabled}
    >${escapeHtml(label)}</button>
  `;
}

function renderRetrievalQualityWarning(
  surface,
  { className = "inline-meta slim" } = {}
) {
  const summary = buildRetrievalQualityWarningSummary(surface);
  const warningKinds = summary.warning_kinds.join(", ") || "none";
  const qualityFlagKinds = summary.quality_flag_kinds.join(", ") || "none";
  return `
    <dl class="${className}" aria-label="검색 품질 경고">
      <div>
        <dt>action</dt>
        <dd>${escapeHtml(summary.recommended_action)}</dd>
      </div>
      <div>
        <dt>message</dt>
        <dd>${escapeHtml(surface.message)}</dd>
      </div>
      <div>
        <dt>warnings</dt>
        <dd>${escapeHtml(summary.warning_count)} · ${escapeHtml(warningKinds)}</dd>
      </div>
      <div>
        <dt>flags</dt>
        <dd>${escapeHtml(summary.quality_flag_count)} · ${escapeHtml(qualityFlagKinds)}</dd>
      </div>
    </dl>
  `;
}

function currentGroundedResponseQualitySurface() {
  return [...workspaceState.messages]
    .reverse()
    .find(message => message.groundedResponseQuality)?.groundedResponseQuality;
}

function renderGroundedResponseQualitySurface(container, surface) {
  const qualitySurface = surface || buildGroundedResponseQualitySurface({});
  container.hidden = !qualitySurface.visible;
  container.dataset.severity = qualitySurface.severity;
  container.dataset.action = qualitySurface.recommended_action;
  container.dataset.boundaryStatus = qualitySurface.boundary_status;
  container.innerHTML = qualitySurface.visible
    ? renderGroundedResponseQuality(qualitySurface)
    : "";
}

function renderGroundedResponseQuality(
  surface,
  { className = "inline-meta slim" } = {}
) {
  const summary = buildGroundedResponseQualitySummary(surface);
  return `
    <dl class="${className}" aria-label="응답 인용 품질">
      <div>
        <dt>action</dt>
        <dd>${escapeHtml(summary.recommended_action)}</dd>
      </div>
      <div>
        <dt>boundary</dt>
        <dd>${escapeHtml(summary.boundary_status)} · ${escapeHtml(summary.citation_status)}</dd>
      </div>
      <div>
        <dt>issues</dt>
        <dd>${escapeHtml(summary.issue_count)}</dd>
      </div>
      <div>
        <dt>lineage</dt>
        <dd>${escapeHtml(summary.retrieval_package_id_present)} · ${escapeHtml(summary.structured_draft_id_present)}</dd>
      </div>
    </dl>
  `;
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
  workspaceState.operations.documentDetail = markOperationRunning(
    workspaceState.operations.documentDetail,
    {
      clientMode: workspaceState.documentDetailClient.clientMode,
      route: documentDetailRoute(documentItem.documentId)
    }
  );
  documentDetailStatus.textContent = statusLabel("RUNNING");
  documentDetailStatus.className = `badge ${badgeClass("RUNNING")}`;
  documentDetail.classList.add("is-loading");
  renderDocumentDetailFeedback();

  let surface;
  try {
    surface = await workspaceState.documentDetailClient.getDocumentDetail(
      documentItem.documentId
    );
  } catch (error) {
    if (requestSequence !== documentDetailRequestSequence) return;
    workspaceState.operations.documentDetail = markOperationFailed(
      workspaceState.operations.documentDetail,
      {
        error,
        clientMode: workspaceState.documentDetailClient.clientMode,
        route: documentDetailRoute(documentItem.documentId)
      }
    );
    renderDocumentDetailError(error);
    return;
  }

  if (requestSequence !== documentDetailRequestSequence) return;
  workspaceState.operations.documentDetail = markOperationSucceeded(
    workspaceState.operations.documentDetail,
    {
      status: surface.processingStatus,
      resultStatus: surface.processingStatus,
      clientMode: surface.clientMode,
      route: surface.detailRoute
    }
  );
  const operation = buildOperationStateSummary(workspaceState.operations.documentDetail);
  documentDetail.classList.remove("is-loading");
  documentDetailStatus.textContent = statusLabel(surface.processingStatus);
  documentDetailStatus.className = `badge ${badgeClass(surface.processingStatus)}`;
  renderDocumentDetailFeedback();
  renderRuntimeDiagnostics();
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
        <dt>operation</dt>
        <dd>${escapeHtml(operation.phase)} · attempt ${escapeHtml(operation.attempt)}</dd>
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
  const operation = buildOperationStateSummary(workspaceState.operations.documentDetail);
  documentDetail.classList.remove("is-loading");
  documentDetailStatus.textContent = statusLabel("UNAVAILABLE");
  documentDetailStatus.className = `badge ${badgeClass("UNAVAILABLE")}`;
  renderDocumentDetailFeedback();
  renderRuntimeDiagnostics();
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
      <div>
        <dt>operation</dt>
        <dd>${escapeHtml(operation.phase)} · attempt ${escapeHtml(operation.attempt)}</dd>
      </div>
    </dl>
  `;
}

function renderDocumentDetailFeedback() {
  renderOperationFeedback(
    documentDetailFeedback,
    documentDetailRetryButton,
    workspaceState.operations.documentDetail,
    {
      operationLabel: "문서 상세",
      idleMessage: "문서 상세 조회 준비가 완료되었습니다.",
      runningMessage: "문서 상세를 불러오고 있습니다.",
      succeededMessage: "문서 상세를 불러왔습니다.",
      failedMessage: "문서 상세를 불러오지 못했습니다."
    }
  );
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

async function appendPromptInteraction() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    promptInput.focus();
    return;
  }

  const format = formatSelect.value;
  const grounded = retrievalToggle.checked;
  const retrievalRequest = buildRetrievalRequest({
    userMessage: prompt,
    chatDocumentId: workspaceState.chatDocumentId,
    documentScope: workspaceState.documentScope,
    grounded
  });
  const retrievalResult = await submitRetrievalRequest(retrievalRequest);
  workspaceState.messages.push({
    role: "user",
    label: "사용자",
    text: prompt
  });
  workspaceState.messages.push({
    role: "assistant",
    label: "assistant",
    text: grounded
      ? `${documentScopeLabel(workspaceState.documentScope)} 범위로 ${retrievalResult.cxStatus} retrieval 결과와 ${format} handoff를 연결했습니다.`
      : `${format} 생성 요청을 일반 답변 흐름으로 연결했습니다.`,
    artifactRefs: [buildMockArtifactRef(format, grounded)],
    retrievalScope: grounded ? workspaceState.documentScope : null,
    retrievalResult: grounded ? retrievalResult : null,
    retrievalQualityWarning: grounded
      ? buildRetrievalQualityWarningSurface(retrievalResult)
      : null,
    groundedResponseQuality: buildGroundedResponseQualitySurface({
      generation: {
        grounded_response_quality: grounded
          ? buildMockGroundedResponseQualityContract(true, {
              boundary_status:
                retrievalResult.cxStatus === "READY" ? "PASS" : "UNKNOWN",
              citation_status:
                retrievalResult.cxStatus === "READY" ? "VALIDATED" : "UNKNOWN",
              issue_count: retrievalResult.cxStatus === "READY" ? 0 : 1,
              recommended_action:
                retrievalResult.cxStatus === "READY"
                  ? "proceed"
                  : "proceed_with_caveat"
            })
          : buildMockGroundedResponseQualityContract(false)
      }
    }),
    generationFeedback: createGenerationFeedbackSurfaceState({
      interactionId: workspaceState.interactionId,
      chatDocumentId: workspaceState.chatDocumentId,
      cxGenerationId: workspaceState.cxGenerationId,
      clientMode: workspaceState.generationFeedbackClient.clientMode
    }),
    repairedResponseReview: grounded
      ? buildRepairedResponseReviewSurfaceFromProjection(
          buildMockRepairedResponseReviewProjection({
            interactionId: workspaceState.interactionId,
            chatDocumentId: workspaceState.chatDocumentId,
            originalGenerationId: workspaceState.cxGenerationId,
            repairedGenerationId: `${workspaceState.cxGenerationId}-repair`,
            retrievalPackageId:
              retrievalResult.cxRetrievalPackageId || workspaceState.retrievalPackageId,
            clientMode: workspaceState.repairedResponseReviewClient.clientMode
          }),
          {
            clientMode: workspaceState.repairedResponseReviewClient.clientMode
          }
        )
      : null
  });
  workspaceState.lastRetrievalRequest = retrievalRequest;
  workspaceState.lastRetrievalResult = retrievalResult;
  workspaceState.artifact.targetFormats = [format];
  workspaceState.artifact.handoffStatus = "READY";
  workspaceState.artifact.citationStatus = grounded ? "VALIDATED" : "NOT_REQUIRED";
  workspaceState.artifact.currentVersionId = workspaceState.artifactRef.artifactVersionId;
  workspaceState.artifact.previewRoute = workspaceState.artifactRef.previewRoute;
  workspaceState.artifact.downloadRoutes = workspaceState.artifactRef.downloadRoutes;
  workspaceState.progressEvents = buildProgressEvents(grounded);
  renderWorkspace();
}

async function submitGenerationFeedback(interactionId, feedbackValue) {
  const targetMessage = workspaceState.messages.find(
    message => message.generationFeedback?.interaction_id === interactionId
  );
  if (!targetMessage) return;

  const ownerScope =
    ownerScopeFromSessionState(workspaceState.sessionState) || localOwnerScope;
  targetMessage.generationFeedback = updateGenerationFeedbackSurface(
    targetMessage.generationFeedback,
    {
    feedbackValue,
    selectedReasons: feedbackReasonsForValue(feedbackValue),
    status: "SUBMITTING",
    reason: "feedback_submit_requested",
    clientMode: workspaceState.generationFeedbackClient.clientMode
    }
  );
  renderMessages();

  try {
    const feedbackRequest = buildGenerationFeedbackRequest({
      tenantId: ownerScope.tenantId,
      userId: ownerScope.ownerUserId,
      interactionId,
      chatDocumentId: targetMessage.generationFeedback.chat_document_id,
      cxGenerationId: targetMessage.generationFeedback.cx_generation_id,
      feedbackValue,
      feedbackReasons: feedbackReasonsForValue(feedbackValue),
      qualityIssueRefs:
        feedbackValue === "negative"
          ? [
              {
                source_service: "nex-ae-api",
                issue_type: "user_reported",
                issue_code: "ae_web_generation_feedback_negative",
                issue_ref_id: targetMessage.generationFeedback.cx_generation_id
              }
            ]
          : []
    });
    const result =
      await workspaceState.generationFeedbackClient.submitGenerationFeedback(
        feedbackRequest
      );
    targetMessage.generationFeedback = updateGenerationFeedbackSurface(
      targetMessage.generationFeedback,
      {
      feedbackValue: result.feedbackValue,
      selectedReasons: feedbackReasonsForValue(result.feedbackValue),
      status: result.status,
      reason: "feedback_recorded",
      route: result.route,
      feedbackId: result.feedbackId,
      clientMode: result.clientMode
      }
    );
  } catch (error) {
    targetMessage.generationFeedback = updateGenerationFeedbackSurface(
      targetMessage.generationFeedback,
      {
      feedbackValue,
      selectedReasons: feedbackReasonsForValue(feedbackValue),
      status: "FAILED",
      reason: "feedback_failed",
      errorStatus: error.status || "GENERATION_FEEDBACK_FAILED",
      clientMode: workspaceState.generationFeedbackClient.clientMode
      }
    );
  }
  renderMessages();
  renderRuntimeDiagnostics();
}

function updateGenerationFeedbackSurface(surface, overrides = {}) {
  return createGenerationFeedbackSurfaceState({
    interactionId: surface.interaction_id,
    chatDocumentId: surface.chat_document_id,
    cxGenerationId: surface.cx_generation_id,
    feedbackValue: surface.feedback_value,
    selectedReasons: surface.selected_reasons,
    status: surface.status,
    reason: surface.reason,
    route: surface.route,
    feedbackId: surface.feedback_id,
    errorStatus: surface.error_status,
    clientMode: surface.client_mode,
    ...overrides
  });
}

function feedbackReasonsForValue(value) {
  if (value === "positive") return ["helpful"];
  if (value === "negative") return ["not_helpful"];
  return ["other"];
}

async function submitRetrievalRequest(retrievalRequest) {
  workspaceState.operations.retrieval = markOperationRunning(
    workspaceState.operations.retrieval,
    {
      clientMode: workspaceState.retrievalClient.clientMode,
      route: retrievalRequest.route
    }
  );
  renderRetrievalScope();
  try {
    const result = await workspaceState.retrievalClient.submitRetrievalRequest(
      retrievalRequest
    );
    workspaceState.operations.retrieval = markOperationSucceeded(
      workspaceState.operations.retrieval,
      {
        status: result.status,
        resultStatus: result.cxStatus,
        clientMode: result.clientMode,
        route: result.route
      }
    );
    return result;
  } catch (error) {
    workspaceState.operations.retrieval = markOperationFailed(
      workspaceState.operations.retrieval,
      {
        error,
        clientMode: workspaceState.retrievalClient.clientMode,
        route: retrievalRequest.route
      }
    );
    return {
      clientMode: workspaceState.retrievalClient.clientMode,
      route: retrievalRequest.route,
      retrievalInteractionId: null,
      chatDocumentId: retrievalRequest.chat_document_id,
      status: "UNAVAILABLE",
      cxStatus: error.status || "RETRIEVAL_CLIENT_ERROR",
      cxRetrievalPackageId: null,
      evidenceCount: 0,
      bestScore: null,
      confidenceBucket: "UNKNOWN",
      noAnswerReason: null,
      warnings: [],
      qualityWarnings: {
        contract_schema_version: "ae_chat_retrieval_quality_warning.v1",
        warning_count: 0,
        warning_kinds: [],
        quality_flag_count: 0,
        quality_flag_kinds: [],
        low_confidence_threshold: null,
        best_score_below_threshold: false,
        status_caveat_required: false,
        recommended_action: "show_error",
        raw_warning_details_included: false
      },
      retryable: Boolean(error.retryable),
      metadata: {
        userMessageIncluded: false,
        sourcePreviewIncluded: false,
        browserServiceTokenIncluded: false,
        providerUrlIncluded: false
      }
    };
  }
}

async function retryLastRetrievalRequest() {
  if (!workspaceState.lastRetrievalRequest) return;
  workspaceState.lastRetrievalResult = await submitRetrievalRequest(
    workspaceState.lastRetrievalRequest
  );
  renderRetrievalScope();
}

async function submitUploadDraft() {
  workspaceState.operations.upload = markOperationRunning(workspaceState.operations.upload, {
    clientMode: workspaceState.uploadClient.clientMode,
    route: workspaceState.uploadDraft.uploadRoute
  });
  uploadSubmitButton.disabled = true;
  uploadRetryButton.disabled = true;
  uploadStatus.textContent = statusLabel("RUNNING");
  uploadStatus.className = `badge ${badgeClass("RUNNING")}`;
  renderOperationFeedback(uploadFeedback, uploadRetryButton, workspaceState.operations.upload, {
    operationLabel: "업로드 전송",
    idleMessage: "업로드 전송 준비가 완료되었습니다.",
    runningMessage: "업로드 handoff를 전송하고 있습니다.",
    succeededMessage: "업로드 handoff가 접수되었습니다.",
    failedMessage: "업로드 handoff를 완료하지 못했습니다."
  });

  try {
    const selectedFile = uploadFileInput.files?.[0] || null;
    workspaceState.uploadSubmission =
      await workspaceState.uploadClient.submitUploadDraft(workspaceState.uploadDraft, {
        file: selectedFile
      });
    workspaceState.operations.upload = markOperationSucceeded(
      workspaceState.operations.upload,
      {
        status: workspaceState.uploadSubmission.status,
        resultStatus: workspaceState.uploadSubmission.dedupeStatus,
        clientMode: workspaceState.uploadSubmission.clientMode,
        route: workspaceState.uploadSubmission.uploadRoute
      }
    );
  } catch (error) {
    workspaceState.operations.upload = markOperationFailed(workspaceState.operations.upload, {
      error,
      clientMode: workspaceState.uploadClient.clientMode,
      route: workspaceState.uploadDraft.uploadRoute
    });
    workspaceState.uploadSubmission = {
      clientMode: workspaceState.uploadClient.clientMode,
      uploadRoute: workspaceState.uploadDraft.uploadRoute,
      status: "UNAVAILABLE",
      dedupeStatus: error.status || "UPLOAD_CLIENT_ERROR",
      uploadHandoffId: null,
      documentId: null,
      retryable: Boolean(error.retryable),
      metadata: {
        sourceContentIncluded: false,
        browserServiceTokenIncluded: false,
        cxStorageIncluded: false,
        providerUrlIncluded: false
      }
    };
  } finally {
    uploadSubmitButton.disabled = false;
    renderUploadSurface();
  }
}

function renderRuntimeDiagnostics() {
  const diagnostics = buildRuntimeDiagnostics({
    runtimeConfig: workspaceState.runtimeConfig,
    sessionState: workspaceState.sessionState,
    sessionBootstrap: workspaceState.sessionBootstrap,
    authBoundary: workspaceState.authBoundary,
    clientRegistry: workspaceState.clientRegistry,
    sessionRouteGuard: workspaceState.sessionRouteGuard,
    operations: workspaceState.operations
  });
  const summary = buildRuntimeDiagnosticsSummary(diagnostics);
  const diagnosticsStatus =
    summary.failed_operation_count > 0 ? "DEGRADED" : "READY";

  runtimeDiagnosticsStatus.textContent = statusLabel(diagnosticsStatus);
  runtimeDiagnosticsStatus.className = `badge ${badgeClass(diagnosticsStatus)}`;
  runtimeDiagnosticsSummary.innerHTML = `
    <div>
      <dt>schema</dt>
      <dd>${escapeHtml(summary.runtime_diagnostics_schema_version)}</dd>
    </div>
    <div>
      <dt>mode</dt>
      <dd>${escapeHtml(summary.client_mode)}</dd>
    </div>
    <div>
      <dt>base</dt>
      <dd>${escapeHtml(summary.ae_base_url || "same-origin")}</dd>
    </div>
    <div>
      <dt>fetch</dt>
      <dd>${escapeHtml(summary.fetch_clients_enabled)} · allowed ${escapeHtml(summary.fetch_mode_allowed)}</dd>
    </div>
    <div>
      <dt>session</dt>
      <dd>${escapeHtml(summary.session_state)} · ${escapeHtml(summary.session_bootstrap_phase)}</dd>
    </div>
    <div>
      <dt>bootstrap</dt>
      <dd>${escapeHtml(buildSessionBootstrapSummary(workspaceState.sessionBootstrap).active_client_mode)}</dd>
    </div>
    <div>
      <dt>guard</dt>
      <dd>${escapeHtml(summary.route_guard_status)}</dd>
    </div>
    <div>
      <dt>operations</dt>
      <dd>${escapeHtml(summary.operation_count)} total · ${escapeHtml(summary.failed_operation_count)} failed · ${escapeHtml(summary.retryable_operation_count)} retryable</dd>
    </div>
  `;
  runtimeDiagnosticsPreview.textContent = JSON.stringify(diagnostics, null, 2);
}

function renderOperationFeedback(container, retryButton, operationState, copy) {
  const feedback = buildOperationFeedback(operationState, copy);
  container.textContent = feedback.message;
  container.dataset.severity = feedback.severity;
  container.dataset.phase = feedback.phase;
  retryButton.hidden = !feedback.retry.available;
  retryButton.disabled = !feedback.retry.enabled;
  retryButton.textContent = feedback.retry.label;
  retryButton.setAttribute("aria-label", feedback.retry.aria_label);
}

function safeUploadPreview(payload, draft, submission) {
  const fileMetadata = draft.fileMetadata || workspaceState.uploadFileMetadata;
  const preview = {
    workspace_id: payload.workspace_id,
    filename: payload.filename,
    content_type: payload.content_type,
    size_bytes: payload.size_bytes,
    source_sha256: payload.source_sha256,
    tenant_id: payload.tenant_id,
    owner_user_id: payload.owner_user_id,
    uploaded_by_user_id: payload.uploaded_by_user_id,
    ownership_ref: payload.ownership_ref,
    file_metadata: {
      schema: fileMetadata.upload_file_metadata_schema_version,
      filename: fileMetadata.filename,
      content_type: fileMetadata.contentType,
      size_bytes: fileMetadata.sizeBytes,
      source_sha256_present: Boolean(fileMetadata.sourceSha256),
      file_selected: fileMetadata.fileSelected,
      metadata: fileMetadata.metadata
    },
    client: {
      mode: workspaceState.uploadClient.clientMode,
      route: draft.uploadRoute,
      authenticated_runtime: buildAuthenticatedRuntimeSummary(
        workspaceState.authenticatedRuntime
      ),
      registry: buildClientRegistrySummary(workspaceState.clientRegistry),
      runtime_config: buildRuntimeConfigSummary(workspaceState.runtimeConfig)
    },
    operation: buildOperationStateSummary(workspaceState.operations.upload),
    metadata: draft.metadata
  };
  if (submission) {
    preview.submission = {
      status: submission.status,
      dedupe_status: submission.dedupeStatus,
      upload_handoff_id: submission.uploadHandoffId,
      document_id: submission.documentId,
      retryable: submission.retryable,
      metadata: submission.metadata
    };
  }
  return preview;
}

function safeRetrievalPreview(retrievalRequest, currentScope, retrievalResult) {
  if (!retrievalRequest) {
    return {
      route: currentScope.route,
      document_scope: currentScope.document_scope,
      selected_count: currentScope.selectedCount,
      client: {
        mode: workspaceState.retrievalClient.clientMode,
        authenticated_runtime: buildAuthenticatedRuntimeSummary(
          workspaceState.authenticatedRuntime
        ),
        registry: buildClientRegistrySummary(workspaceState.clientRegistry),
        runtime_config: buildRuntimeConfigSummary(workspaceState.runtimeConfig),
        operation: buildOperationStateSummary(workspaceState.operations.retrieval)
      },
      status: "READY_FOR_PROMPT"
    };
  }
  const preview = {
    route: retrievalRequest.route,
    chat_document_id: retrievalRequest.chat_document_id,
    execution_mode: retrievalRequest.retrieval.execution_mode,
    document_scope: retrievalRequest.retrieval.document_scope,
    retrieval_profile: retrievalRequest.retrieval.retrieval_profile,
    top_k: retrievalRequest.retrieval.top_k,
    include_source_preview: retrievalRequest.retrieval.include_source_preview,
    purpose: retrievalRequest.retrieval.purpose,
    selected_count: retrievalRequest.surface.selected_count
  };
  if (retrievalResult) {
    preview.client = {
      mode: retrievalResult.clientMode,
      status: retrievalResult.status,
      cx_status: retrievalResult.cxStatus,
      retrieval_interaction_id: retrievalResult.retrievalInteractionId,
      cx_retrieval_package_id: retrievalResult.cxRetrievalPackageId,
      evidence_count: retrievalResult.evidenceCount,
      best_score: retrievalResult.bestScore,
      confidence_bucket: retrievalResult.confidenceBucket,
      no_answer_reason: retrievalResult.noAnswerReason,
      quality_warning: buildRetrievalQualityWarningSummary(
        buildRetrievalQualityWarningSurface(retrievalResult)
      ),
      grounded_response_quality: buildGroundedResponseQualitySummary(
        buildGroundedResponseQualitySurface({
          generation: {
            grounded_response_quality: buildMockGroundedResponseQualityContract(
              retrievalResult.cxStatus !== "NOT_REQUESTED"
            )
          }
        })
      ),
      retryable: retrievalResult.retryable,
      operation: buildOperationStateSummary(workspaceState.operations.retrieval),
      metadata: retrievalResult.metadata
    };
  }
  return preview;
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

function buildMockGroundedResponseQualityContract(grounded, overrides = {}) {
  return {
    contract_schema_version: "ae_chat_grounded_response_quality.v1",
    source_audit_schema_version: grounded
      ? "cx_grounded_response_citation_quality_audit.v1"
      : null,
    boundary_status: grounded ? "PASS" : "NOT_REQUIRED",
    citation_status: grounded ? "VALIDATED" : "NOT_REQUIRED",
    issue_count: 0,
    recommended_action: "proceed",
    grounding_required: grounded,
    retrieval_package_id: grounded ? "cx-ret-local" : null,
    retrieval_package_hash: grounded ? "d".repeat(64) : null,
    structured_draft_id: grounded ? "draft-local-001" : null,
    raw_output_included: false,
    evidence_text_included: false,
    prompt_text_included: false,
    provider_detail_included: false,
    ...overrides
  };
}

function buildMockRepairedResponseReviewProjection({
  interactionId = "interaction-local",
  chatDocumentId = "chat-doc-local",
  repairedResponseHandoffId = "handoff-local-repair-001",
  handoffRequestId = "request-local-repair-001",
  originalGenerationId = "cx-gen-local",
  repairedGenerationId = "cx-gen-local-repair",
  retrievalPackageId = "cx-ret-local",
  outputPreview = "근거 누락 지점을 보강한 수정 응답입니다."
} = {}) {
  const redactionSummary = {
    raw_output_included: false,
    ["raw_" + "prompt_included"]: false,
    ["raw_" + "source_" + "text_included"]: false,
    ["evidence_" + "text_included"]: false,
    provider_detail_included: false,
    ["storage_" + "path_included"]: false
  };
  return {
    projection_schema_version: "ae_repaired_response_review_projection.v1",
    projection_status: "READY_FOR_DECISION",
    repaired_response_handoff_id: repairedResponseHandoffId,
    handoff_request_id: handoffRequestId,
    trace_id: "trace-local-repair",
    request_id: "request-local-repair",
    owner_scope: {
      tenant_id: localOwnerScope.tenantId,
      workspace_id: "workspace-local",
      owner_user_id: localOwnerScope.ownerUserId
    },
    conversation_scope: {
      chat_document_id: chatDocumentId,
      interaction_id: interactionId
    },
    review_card: {
      title: "수정 응답 검토",
      presentation_mode: "side_by_side_review",
      default_action: "review_repair"
    },
    original_response_ref: {
      cx_generation_id: originalGenerationId,
      link: `/api/v1/generations/${originalGenerationId}`,
      parent_generation_mutated: false
    },
    repaired_response_summary: {
      cx_generation_id: repairedGenerationId,
      status: "SUCCEEDED",
      alias: "default",
      provider_capability: "grounded_generation",
      finish_reason: "stop",
      output_hash: "a".repeat(64),
      output_preview: outputPreview,
      usage: {
        input_tokens: 120,
        output_tokens: 80,
        total_tokens: 200
      },
      quality_summary: {
        grounding_required: true,
        retrieval_package_id: retrievalPackageId,
        grounded_response_quality_status: "PASS"
      }
    },
    lineage_summary: {
      remediation_action_id: "remediation-local-001",
      lineage_status: "REPAIRED",
      action_type: "regenerate_answer",
      lineage_type: "repair",
      attempt_no: 2,
      result_ref: {
        kind: "cx_generation",
        id: repairedGenerationId
      }
    },
    decision_controls: {
      available_actions: [
        "view_original",
        "view_repaired",
        "accept_repair",
        "keep_original",
        "view_lineage"
      ],
      primary_actions: ["accept_repair", "keep_original"],
      secondary_actions: ["view_original", "view_repaired", "view_lineage"],
      decision_submit_path:
        `/api/v1/chat/interactions/${interactionId}/` +
        `repaired-response-handoffs/${repairedResponseHandoffId}/decisions`,
      idempotency_key_hint: handoffRequestId
    },
    links: {
      handoff:
        `/api/v1/chat/interactions/${interactionId}/` +
        `repaired-response-handoffs/${repairedResponseHandoffId}`,
      original_generation: `/api/v1/generations/${originalGenerationId}`,
      repaired_generation: `/api/v1/generations/${repairedGenerationId}`,
      remediation_execution:
        `/api/v1/generations/${originalGenerationId}/` +
        "remediation-executions/remediation-local-001"
    },
    redaction_summary: redactionSummary,
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:01:00Z",
    checked_at: "2026-08-27T00:02:00Z"
  };
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
  if (["HEALTHY", "READY", "VALIDATED", "SUCCEEDED", "HIGH", "COMPLETED"].includes(status)) {
    return "success";
  }
  if ([
    "DEGRADED",
    "LOW_CONFIDENCE",
    "MEDIUM",
    "PREVIEW_ONLY",
    "READY_FOR_HANDOFF",
    "READY_FOR_PROMPT",
    "READY_FOR_SUBMIT",
    "ALREADY_EXISTS",
    "QUEUED"
  ].includes(status)) {
    return "warning";
  }
  if (["RUNNING", "READY_FOR_RENDERING"].includes(status)) return "running";
  if (["PENDING", "UNKNOWN", "NOT_REQUIRED"].includes(status)) return "pending";
  return "danger";
}

function statusLabel(status) {
  const labels = {
    COMPLETED: "완료",
    SKIPPED: "건너뜀",
    RUNNING: "진행",
    QUEUED: "대기열",
    READY: "준비",
    ALREADY_EXISTS: "이미 있음",
    READY_FOR_HANDOFF: "전달 준비",
    READY_FOR_PROMPT: "입력 준비",
    READY_FOR_SUBMIT: "전송 준비",
    READY_FOR_RENDERING: "렌더링 준비",
    READY_FOR_LOGIN: "로그인 준비",
    SUBMITTING: "전송 중",
    AUTHENTICATED: "인증됨",
    FAILED: "실패",
    LOGGED_OUT: "로그아웃",
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
