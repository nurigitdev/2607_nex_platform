import {
  AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION,
  buildArtifactCardReadModelSummary,
  buildArtifactCardViewModel
} from "./artifactCardReadModel.js";

export const AE_WEB_ARTIFACT_CARD_RENDERER_SCHEMA_VERSION =
  "ae_web_artifact_card_renderer.v1";

export function renderArtifactCard(source, options = {}) {
  const viewModel = asArtifactCardViewModel(source, options);
  return `
    <section
      class="artifact-link artifact-card"
      data-artifact-card="${escapeAttribute(viewModel.artifactId)}"
      data-artifact-id="${escapeAttribute(viewModel.artifactId)}"
      data-artifact-status="${escapeAttribute(viewModel.artifactStatus)}"
      data-artifact-version-id="${escapeAttribute(viewModel.artifactVersionId || "")}"
      aria-label="연결된 아티팩트"
    >
      <header class="artifact-link-heading artifact-card-header">
        <strong>${escapeHtml(viewModel.displayTitle)}</strong>
        <span class="badge ${badgeClass(viewModel.artifactStatus)}">${escapeHtml(statusLabel(viewModel.artifactStatus))}</span>
      </header>
      <dl class="inline-meta slim artifact-card-meta">
        <div>
          <dt>format</dt>
          <dd>${escapeHtml(viewModel.primaryFormat)}</dd>
        </div>
        <div>
          <dt>version</dt>
          <dd>${escapeHtml(viewModel.artifactVersionId || "pending")}</dd>
        </div>
        <div>
          <dt>source</dt>
          <dd>${escapeHtml(viewModel.sourceGenerationId || "n/a")}</dd>
        </div>
        <div>
          <dt>citations</dt>
          <dd>${escapeHtml(viewModel.qualitySummary.citationStatus)} · ${escapeHtml(viewModel.qualitySummary.evidenceRefCount)}</dd>
        </div>
      </dl>
      <div class="artifact-actions artifact-card-actions">
        ${renderPreviewAction(viewModel)}
        ${viewModel.downloadActions.map(renderDownloadAction).join("")}
        ${viewModel.secondaryActions.map(renderSecondaryAction).join("")}
      </div>
      ${renderWarnings(viewModel)}
    </section>
  `;
}

export function buildArtifactCardRendererSummary(source, options = {}) {
  const viewModel = asArtifactCardViewModel(source, options);
  const summary = buildArtifactCardReadModelSummary(viewModel);
  const rendererSummary = {
    artifact_card_renderer_schema_version:
      AE_WEB_ARTIFACT_CARD_RENDERER_SCHEMA_VERSION,
    artifact_card_schema_version: summary.artifact_card_schema_version,
    artifact_id: summary.artifact_id,
    artifact_status: summary.artifact_status,
    rendered_action_count:
      1 + summary.download_action_count + summary.secondary_action_count,
    enabled_action_count:
      Number(summary.preview_enabled) + summary.enabled_download_action_count,
    warning_count: summary.warning_count,
    client_mode: summary.client_mode,
    metadata: {
      ...summary.metadata,
      htmlEscaped: true,
      contentRendered: false
    }
  };
  assertRenderedArtifactCardSafe(rendererSummary);
  return rendererSummary;
}

export function assertRenderedArtifactCardSafe(value) {
  const serialized = typeof value === "string" ? value : JSON.stringify(value);
  if (
    /raw_prompt|raw_source|source_text|service_token|database_url|provider_url|storage_ref|storage_path|\/data\/nex-platform/i.test(
      serialized
    )
  ) {
    throw new Error("Rendered artifact card contains unsafe fields.");
  }
}

function asArtifactCardViewModel(source, options) {
  if (
    source?.artifact_card_schema_version ===
    AE_WEB_ARTIFACT_CARD_READ_MODEL_SCHEMA_VERSION
  ) {
    return source;
  }
  return buildArtifactCardViewModel(source, options);
}

function renderPreviewAction(viewModel) {
  const action = viewModel.previewAction;
  if (!action.enabled) {
    return `
      <button
        type="button"
        data-artifact-preview-action="${escapeAttribute(viewModel.artifactId)}"
        data-artifact-action="preview"
        disabled
      >Preview</button>
    `;
  }
  return `
    <a
      href="${escapeAttribute(action.route)}"
      data-artifact-preview-action="${escapeAttribute(viewModel.artifactId)}"
      data-artifact-action="preview"
      data-artifact-preview-route="${escapeAttribute(action.route)}"
    >Preview</a>
  `;
}

function renderDownloadAction(action) {
  if (!action.enabled) {
    return `
      <button
        type="button"
        data-artifact-action="download"
        data-artifact-download-format="${escapeAttribute(action.format)}"
        disabled
      >${escapeHtml(action.label)}</button>
    `;
  }
  return `
    <a
      href="${escapeAttribute(action.route)}"
      data-artifact-action="download"
      data-artifact-download-format="${escapeAttribute(action.format)}"
      data-artifact-download-route="${escapeAttribute(action.route)}"
    >${escapeHtml(action.label)}</a>
  `;
}

function renderSecondaryAction(action) {
  return `
    <button
      type="button"
      data-artifact-secondary-action="${escapeAttribute(action.action)}"
      aria-disabled="${action.enabled ? "false" : "true"}"
      ${action.enabled ? "" : "disabled"}
    >${escapeHtml(action.label)}</button>
  `;
}

function renderWarnings(viewModel) {
  if (viewModel.warnings.length === 0) return "";
  return `
    <ul class="artifact-card-warnings" aria-label="아티팩트 경고">
      ${viewModel.warnings
        .map(
          warning =>
            `<li data-severity="${escapeAttribute(warning.severity)}">${escapeHtml(warning.message)}</li>`
        )
        .join("")}
    </ul>
  `;
}

function badgeClass(status) {
  if (status === "READY" || status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "ERROR") return "danger";
  if (status === "RUNNING" || status === "DRAFT") return "running";
  return "pending";
}

function statusLabel(status) {
  return String(status || "UNKNOWN").replaceAll("_", " ");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
