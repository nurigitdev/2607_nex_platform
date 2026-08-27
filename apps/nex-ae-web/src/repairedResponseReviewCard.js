import {
  buildRepairedResponseReviewSurfaceSummary
} from "./repairedResponseReviewClient.js";

export const AE_WEB_REPAIRED_RESPONSE_REVIEW_CARD_SCHEMA_VERSION =
  "ae_web_repaired_response_review_card.v1";

const PRIMARY_ACTION_LABELS = {
  accept_repair: "수정본 적용",
  keep_original: "원본 유지"
};

const SECONDARY_ACTION_LABELS = {
  view_original: "원본",
  view_repaired: "수정본",
  view_lineage: "lineage"
};

const TERMINAL_DECISION_STATUSES = new Set(["RECORDED", "ACCEPTED", "KEPT"]);

export function buildRepairedResponseReviewCardViewModel(
  surface,
  { decisionEnabled = false, decisionState = null } = {}
) {
  const summary = buildRepairedResponseReviewSurfaceSummary(surface);
  const normalizedDecision = normalizeDecisionState(decisionState);
  const viewModel = {
    card_schema_version: AE_WEB_REPAIRED_RESPONSE_REVIEW_CARD_SCHEMA_VERSION,
    review_surface_schema_version: summary.review_surface_schema_version,
    repairedResponseHandoffId: summary.repaired_response_handoff_id,
    interactionId: summary.interaction_id,
    chatDocumentId: summary.chat_document_id,
    title: nonEmptyText(surface.title, "Repaired response review"),
    projectionStatus: summary.projection_status,
    presentationMode: summary.presentation_mode,
    repairedStatus: summary.repaired_status,
    repairedGenerationId: summary.repaired_generation_id,
    originalGenerationId: summary.original_generation_id,
    lineageStatus: summary.lineage_status,
    remediationActionId: nonEmptyText(surface.remediationActionId, "n/a"),
    repairedOutputPreview:
      nonEmptyText(surface.repairedOutputPreview, "") ||
      "수정 응답 미리보기가 없습니다.",
    decisionRoute: summary.decision_route,
    clientMode: summary.client_mode,
    sourceRoute: summary.route,
    primaryActions: buildPrimaryActions(surface, {
      decisionEnabled,
      decisionState: normalizedDecision
    }),
    secondaryLinks: buildSecondaryLinks(surface),
    decisionState: normalizedDecision,
    metadata: {
      ...summary.metadata,
      rawPromptRendered: false,
      rawGenerationOutputRendered: false,
      rawSourceRendered: false,
      serviceTokenRendered: false,
      renderedPreviewKind: "safe_summary_only"
    }
  };
  assertReviewCardViewModelSafe(viewModel);
  return viewModel;
}

export function buildRepairedResponseReviewCardSummary(surface, options = {}) {
  const viewModel = buildRepairedResponseReviewCardViewModel(surface, options);
  return {
    card_schema_version: viewModel.card_schema_version,
    repaired_response_handoff_id: viewModel.repairedResponseHandoffId,
    interaction_id: viewModel.interactionId,
    projection_status: viewModel.projectionStatus,
    repaired_status: viewModel.repairedStatus,
    lineage_status: viewModel.lineageStatus,
    primary_action_count: viewModel.primaryActions.length,
    secondary_link_count: viewModel.secondaryLinks.length,
    enabled_action_count: viewModel.primaryActions.filter(action => !action.disabled)
      .length,
    decision_status: viewModel.decisionState.status,
    client_mode: viewModel.clientMode,
    metadata: viewModel.metadata
  };
}

export function renderRepairedResponseReviewCard(surface, options = {}) {
  const viewModel = buildRepairedResponseReviewCardViewModel(surface, options);
  return `
    <section
      class="repaired-response-review-card"
      data-repaired-response-review-card="${escapeAttribute(viewModel.repairedResponseHandoffId)}"
      data-interaction-id="${escapeAttribute(viewModel.interactionId)}"
      data-projection-status="${escapeAttribute(viewModel.projectionStatus)}"
      aria-label="수정 응답 검토"
    >
      <header class="repaired-response-review-card-header">
        <strong>${escapeHtml(viewModel.title)}</strong>
        <span>${escapeHtml(viewModel.projectionStatus)}</span>
      </header>
      <p class="repaired-response-review-preview">${escapeHtml(viewModel.repairedOutputPreview)}</p>
      <div class="repaired-response-review-actions">
        ${viewModel.primaryActions.map(renderPrimaryAction).join("")}
      </div>
      <div class="repaired-response-review-links">
        ${viewModel.secondaryLinks.map(renderSecondaryLink).join("")}
      </div>
      <dl class="inline-meta slim repaired-response-review-meta">
        <div>
          <dt>repair</dt>
          <dd>${escapeHtml(viewModel.repairedStatus)} · ${escapeHtml(viewModel.repairedGenerationId)}</dd>
        </div>
        <div>
          <dt>lineage</dt>
          <dd>${escapeHtml(viewModel.lineageStatus)} · ${escapeHtml(viewModel.remediationActionId)}</dd>
        </div>
        <div>
          <dt>decision</dt>
          <dd>${escapeHtml(decisionStateDisplay(viewModel))}</dd>
        </div>
      </dl>
    </section>
  `;
}

export function assertReviewCardViewModelSafe(viewModel) {
  const payload = JSON.stringify(viewModel);
  if (
    /raw_prompt|raw_generation_output|raw_source|source_text|service_token|database_url|provider_url|storage_path/i.test(
      payload
    )
  ) {
    throw new Error("Repaired response review card contains unsafe payload fields.");
  }
}

function buildPrimaryActions(surface, { decisionEnabled, decisionState }) {
  const availableActions = Array.isArray(surface.availableActions)
    ? surface.availableActions
    : [];
  return surface.primaryActions.map(action => {
    const actionAvailable = availableActions.includes(action);
    const disabled =
      !decisionEnabled ||
      !actionAvailable ||
      decisionState.status === "SUBMITTING" ||
      TERMINAL_DECISION_STATUSES.has(decisionState.status);
    return {
      action,
      label: PRIMARY_ACTION_LABELS[action] || action.replaceAll("_", " "),
      disabled,
      selected: decisionState.action === action,
      decisionRoute: surface.decisionRoute,
      interactionId: surface.interactionId,
      repairedResponseHandoffId: surface.repairedResponseHandoffId
    };
  });
}

function buildSecondaryLinks(surface) {
  return surface.secondaryActions
    .map(action => {
      const href = secondaryHref(surface, action);
      if (!href) return null;
      return {
        action,
        label: SECONDARY_ACTION_LABELS[action] || action.replaceAll("_", " "),
        href
      };
    })
    .filter(Boolean);
}

function secondaryHref(surface, action) {
  if (action === "view_original") return surface.links?.originalGeneration || null;
  if (action === "view_repaired") return surface.links?.repairedGeneration || null;
  if (action === "view_lineage") return surface.links?.remediationExecution || null;
  return null;
}

function renderPrimaryAction(action) {
  return `
    <button
      type="button"
      data-repaired-response-decision-action="${escapeAttribute(action.action)}"
      data-interaction-id="${escapeAttribute(action.interactionId)}"
      data-handoff-id="${escapeAttribute(action.repairedResponseHandoffId)}"
      data-decision-route="${escapeAttribute(action.decisionRoute)}"
      aria-pressed="${action.selected ? "true" : "false"}"
      ${action.disabled ? "disabled" : ""}
    >${escapeHtml(action.label)}</button>
  `;
}

function renderSecondaryLink(link) {
  return `
    <a
      href="${escapeAttribute(link.href)}"
      data-repaired-response-review-link="${escapeAttribute(link.action)}"
    >${escapeHtml(link.label)}</a>
  `;
}

function decisionStateDisplay(viewModel) {
  if (viewModel.decisionState.errorStatus) {
    return `${viewModel.decisionState.status} · ${viewModel.decisionState.errorStatus}`;
  }
  if (viewModel.decisionState.decisionId) {
    return `${viewModel.decisionState.status} · ${viewModel.decisionState.decisionId}`;
  }
  return `${viewModel.decisionState.status} · ${viewModel.decisionRoute}`;
}

function normalizeDecisionState(decisionState) {
  if (!decisionState || typeof decisionState !== "object") {
    return {
      status: "READY_FOR_DECISION",
      action: null,
      decisionId: null,
      errorStatus: null
    };
  }
  return {
    status: nonEmptyText(decisionState.status, "READY_FOR_DECISION"),
    action: nonEmptyText(decisionState.action, null),
    decisionId: nonEmptyText(decisionState.decisionId, null),
    errorStatus: nonEmptyText(decisionState.errorStatus, null)
  };
}

function nonEmptyText(value, fallback) {
  if (value == null) return fallback;
  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : fallback;
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
