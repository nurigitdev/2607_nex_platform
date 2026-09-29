import {
  buildClientRegistrySummary
} from "./clientRegistry.js";
import {
  buildAuthBoundarySummary
} from "./authBoundary.js";
import {
  buildOperationStateSummary
} from "./operationState.js";
import {
  buildRuntimeConfigSummary
} from "./runtimeConfig.js";
import {
  buildSessionStateSummary
} from "./sessionClient.js";
import {
  buildSessionBootstrapSummary
} from "./sessionBootstrap.js";
import {
  buildSessionRouteGuardSummary
} from "./sessionRouteGuard.js";
import {
  buildRepairedResponseReviewReadModelSummary
} from "./repairedResponseReviewReadModel.js";
import { buildGenerationLifecycleSummary } from "./generationLifecycleState.js";
import { buildGroundedGenerationPresentationSummary } from "./groundedGenerationPresentation.js";

export const AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION =
  "ae_web_runtime_diagnostics.v1";

export class RuntimeDiagnosticsError extends Error {
  constructor(message, { status = "RUNTIME_DIAGNOSTICS_INVALID" } = {}) {
    super(message);
    this.name = "RuntimeDiagnosticsError";
    this.status = status;
  }
}

export function buildRuntimeDiagnostics({
  runtimeConfig,
  sessionState = null,
  sessionBootstrap = null,
  sessionRouteGuard = null,
  authBoundary = null,
  clientRegistry,
  operations = {},
  repairedResponseReviewReadModel = null,
  generationLifecycle = null,
  generationPresentation = null
} = {}) {
  const runtime = buildRuntimeConfigSummary(runtimeConfig);
  const session = sessionState ? buildSessionStateSummary(sessionState) : null;
  const bootstrap = sessionBootstrap
    ? buildSessionBootstrapSummary(sessionBootstrap)
    : null;
  const auth = authBoundary ? buildAuthBoundarySummary(authBoundary) : null;
  const routeGuard = sessionRouteGuard
    ? buildSessionRouteGuardSummary(sessionRouteGuard)
    : null;
  const registry = buildClientRegistrySummary(clientRegistry);
  const operationSummaries = summarizeOperations(operations);
  const repairedReviewSummary = repairedResponseReviewReadModel
    ? buildRepairedResponseReviewReadModelSummary(repairedResponseReviewReadModel)
    : null;
  const generationLifecycleSummary = generationLifecycle
    ? buildGenerationLifecycleSummary(generationLifecycle)
    : null;
  const generationPresentationSummary = generationPresentation
    ? buildGroundedGenerationPresentationSummary(generationPresentation)
    : null;

  return {
    runtime_diagnostics_schema_version: AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
    client_mode: runtime.client_mode,
    session_state: session?.status || "unknown",
    session_bootstrap_phase: bootstrap?.phase || "unknown",
    route_guard_status: routeGuard?.guard_status || "unknown",
    ae_base_url: runtime.ae_base_url,
    fetch_clients_enabled: Boolean(runtime.features.fetch_clients_enabled),
    fetch_mode_allowed: Boolean(auth?.fetch_mode_allowed),
    feature_flags: runtime.features,
    session,
    session_bootstrap: bootstrap,
    session_route_guard: routeGuard,
    auth_boundary: auth,
    registry,
    operations: operationSummaries,
    repaired_response_reviews: repairedReviewSummary,
    generation_lifecycle: generationLifecycleSummary,
    generation_presentation: generationPresentationSummary,
    generation_phase: generationLifecycleSummary?.phase || "idle",
    generation_display_mode:
      generationPresentationSummary?.display_mode || "NONE",
    generation_next_action:
      generationPresentationSummary?.next_action || "NONE",
    generation_artifact_handoff_allowed: Boolean(
      generationPresentationSummary?.artifact_handoff_allowed
    ),
    repaired_response_review_count: repairedReviewSummary?.total_count || 0,
    repaired_response_actionable_count:
      repairedReviewSummary?.actionable_count || 0,
    repaired_response_failed_count: repairedReviewSummary?.failed_count || 0,
    operation_count: operationSummaries.length,
    failed_operation_count: operationSummaries.filter(
      operation => operation.phase === "failed"
    ).length,
    retryable_operation_count: operationSummaries.filter(
      operation => operation.retryable
    ).length,
    metadata: {
      browserCredentialIncluded: false,
      serviceTokenIncluded: false,
      rawPromptRendered: false,
      rawSourceIncluded: false,
      sourcePreviewIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false,
      liveNetworkUsed: false
    }
  };
}

export function buildRuntimeDiagnosticsSummary(diagnostics) {
  if (
    !diagnostics ||
    diagnostics.runtime_diagnostics_schema_version !==
      AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION
  ) {
    throw new RuntimeDiagnosticsError("Runtime diagnostics are invalid.", {
      status: "RUNTIME_DIAGNOSTICS_SCHEMA_INVALID"
    });
  }

  return {
    runtime_diagnostics_schema_version:
      diagnostics.runtime_diagnostics_schema_version,
    client_mode: diagnostics.client_mode,
    session_state: diagnostics.session_state,
    session_bootstrap_phase: diagnostics.session_bootstrap_phase,
    route_guard_status: diagnostics.route_guard_status,
    ae_base_url: diagnostics.ae_base_url,
    fetch_clients_enabled: diagnostics.fetch_clients_enabled,
    fetch_mode_allowed: diagnostics.fetch_mode_allowed,
    operation_count: diagnostics.operation_count,
    failed_operation_count: diagnostics.failed_operation_count,
    retryable_operation_count: diagnostics.retryable_operation_count,
    repaired_response_review_count: diagnostics.repaired_response_review_count,
    repaired_response_actionable_count:
      diagnostics.repaired_response_actionable_count,
    repaired_response_failed_count: diagnostics.repaired_response_failed_count,
    generation_phase: diagnostics.generation_phase,
    generation_display_mode: diagnostics.generation_display_mode,
    generation_next_action: diagnostics.generation_next_action,
    generation_artifact_handoff_allowed:
      diagnostics.generation_artifact_handoff_allowed,
    metadata: diagnostics.metadata
  };
}

function summarizeOperations(operations) {
  if (!operations || typeof operations !== "object" || Array.isArray(operations)) {
    throw new RuntimeDiagnosticsError("Runtime diagnostics operations are invalid.", {
      status: "RUNTIME_DIAGNOSTICS_OPERATIONS_INVALID"
    });
  }
  return Object.values(operations).map(operation =>
    buildOperationStateSummary(operation)
  );
}
