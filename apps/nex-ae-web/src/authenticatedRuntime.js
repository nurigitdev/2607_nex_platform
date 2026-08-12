import {
  auditAuthenticatedRuntimeBoundary,
  buildAuthBoundarySummary
} from "./authBoundary.js";
import {
  buildClientRegistrySummary,
  createAeWebClients
} from "./clientRegistry.js";
import {
  AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION,
  buildRuntimeConfigSummary,
  normalizeRuntimeConfig
} from "./runtimeConfig.js";
import {
  AE_WEB_SESSION_STATE_SCHEMA_VERSION,
  buildSessionClientSummary,
  buildSessionStateSummary,
  createAnonymousSessionState,
  createFetchSessionClient,
  createMockSessionClient
} from "./sessionClient.js";

export const AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION =
  "ae_web_authenticated_runtime.v1";

export class AuthenticatedRuntimeError extends Error {
  constructor(
    message,
    { status = "AUTHENTICATED_RUNTIME_INVALID", blockedReasons = [] } = {}
  ) {
    super(message);
    this.name = "AuthenticatedRuntimeError";
    this.status = status;
    this.blockedReasons = blockedReasons;
  }
}

export function createAuthenticatedAeWebRuntime({
  runtimeConfig = {},
  sessionState = null,
  sessionClient = null,
  sessionSnapshot = null,
  documents = [],
  fetchImpl,
  responseFactories = {}
} = {}) {
  const normalizedRuntimeConfig = normalizeRuntimeConfigInput(runtimeConfig);
  const normalizedSessionState = normalizeSessionStateInput(sessionState);
  const authBoundary = auditAuthenticatedRuntimeBoundary({
    clientMode: normalizedRuntimeConfig.clientMode,
    fetchClientsEnabled: normalizedRuntimeConfig.features.fetch_clients_enabled,
    sessionState: normalizedSessionState.status,
    credentialMode:
      normalizedRuntimeConfig.clientMode === "fetch" ? "same-origin" : "none",
    ownerScopeSource:
      normalizedSessionState.status === "authenticated"
        ? "session-claims"
        : "mock-local",
    runtimeConfig: runtimeConfigForAuthAudit(normalizedRuntimeConfig)
  });

  if (normalizedRuntimeConfig.clientMode === "fetch" && !authBoundary.fetch_mode.allowed) {
    throw new AuthenticatedRuntimeError(
      "Fetch-mode runtime requires an authenticated browser session.",
      {
        status: "AUTHENTICATED_RUNTIME_FETCH_BLOCKED",
        blockedReasons: authBoundary.fetch_mode.blocked_reasons
      }
    );
  }

  const normalizedSessionClient =
    sessionClient ||
    createDefaultSessionClient({
      runtimeConfig: normalizedRuntimeConfig,
      fetchImpl,
      sessionSnapshot
    });
  const clientRegistry = createAeWebClients({
    mode: normalizedRuntimeConfig.clientMode,
    baseUrl: normalizedRuntimeConfig.aeBaseUrl,
    fetchImpl,
    documents,
    responseFactories
  });

  return {
    authenticated_runtime_schema_version: AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION,
    runtimeConfig: normalizedRuntimeConfig,
    sessionState: normalizedSessionState,
    sessionClient: normalizedSessionClient,
    authBoundary,
    clientRegistry,
    metadata: safeRuntimeMetadata()
  };
}

export function buildAuthenticatedRuntimeSummary(runtime) {
  if (
    !runtime ||
    runtime.authenticated_runtime_schema_version !==
      AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION
  ) {
    throw new AuthenticatedRuntimeError("Authenticated runtime summary input is invalid.", {
      status: "AUTHENTICATED_RUNTIME_SUMMARY_INVALID"
    });
  }

  return {
    authenticated_runtime_schema_version:
      runtime.authenticated_runtime_schema_version,
    runtime_config: buildRuntimeConfigSummary(runtime.runtimeConfig),
    session_state: buildSessionStateSummary(runtime.sessionState),
    session_client: buildSessionClientSummary(runtime.sessionClient),
    auth_boundary: buildAuthBoundarySummary(runtime.authBoundary),
    registry: buildClientRegistrySummary(runtime.clientRegistry),
    fetch_mode_allowed: runtime.authBoundary.fetch_mode.allowed,
    metadata: runtime.metadata
  };
}

function normalizeRuntimeConfigInput(runtimeConfig) {
  if (
    runtimeConfig?.runtime_config_schema_version ===
    AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION
  ) {
    return runtimeConfig;
  }
  return normalizeRuntimeConfig(runtimeConfig || {});
}

function normalizeSessionStateInput(sessionState) {
  if (sessionState == null) {
    return createAnonymousSessionState();
  }
  if (
    sessionState.session_state_schema_version !==
      AE_WEB_SESSION_STATE_SCHEMA_VERSION ||
    !["anonymous", "authenticated", "expired"].includes(sessionState.status)
  ) {
    throw new AuthenticatedRuntimeError("Browser session state is invalid.", {
      status: "AUTHENTICATED_RUNTIME_SESSION_INVALID"
    });
  }
  return sessionState;
}

function createDefaultSessionClient({
  runtimeConfig,
  fetchImpl,
  sessionSnapshot
}) {
  if (runtimeConfig.clientMode === "fetch") {
    return createFetchSessionClient({
      baseUrl: runtimeConfig.aeBaseUrl,
      fetchImpl
    });
  }
  return createMockSessionClient({ sessionSnapshot });
}

function runtimeConfigForAuthAudit(runtimeConfig) {
  return {
    runtime_config_schema_version: runtimeConfig.runtime_config_schema_version,
    client_mode: runtimeConfig.clientMode,
    ae_base_url: runtimeConfig.aeBaseUrl,
    features: runtimeConfig.features
  };
}

function safeRuntimeMetadata() {
  return {
    rawTokenStored: false,
    serviceTokenStored: false,
    passwordStored: false,
    providerEndpointIncluded: false,
    databaseEndpointIncluded: false,
    storageLocationIncluded: false,
    browserPayloadAuthoritative: false,
    claimAuthoritativeWhenAuthenticated: true
  };
}
