import {
  buildClientRegistrySummary
} from "./clientRegistry.js";
import {
  buildOperationStateSummary
} from "./operationState.js";
import {
  buildRuntimeConfigSummary
} from "./runtimeConfig.js";

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
  clientRegistry,
  operations = {}
} = {}) {
  const runtime = buildRuntimeConfigSummary(runtimeConfig);
  const registry = buildClientRegistrySummary(clientRegistry);
  const operationSummaries = summarizeOperations(operations);

  return {
    runtime_diagnostics_schema_version: AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
    client_mode: runtime.client_mode,
    ae_base_url: runtime.ae_base_url,
    fetch_clients_enabled: Boolean(runtime.features.fetch_clients_enabled),
    feature_flags: runtime.features,
    registry,
    operations: operationSummaries,
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
    ae_base_url: diagnostics.ae_base_url,
    fetch_clients_enabled: diagnostics.fetch_clients_enabled,
    operation_count: diagnostics.operation_count,
    failed_operation_count: diagnostics.failed_operation_count,
    retryable_operation_count: diagnostics.retryable_operation_count,
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
