import {
  auditAuthenticatedRuntimeBoundary
} from "./authBoundary.js";
import {
  createAeWebClients
} from "./clientRegistry.js";
import {
  AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION,
  AuthenticatedRuntimeError,
  createAuthenticatedAeWebRuntime
} from "./authenticatedRuntime.js";
import {
  AE_WEB_RUNTIME_CONFIG_SCHEMA_VERSION,
  normalizeRuntimeConfig
} from "./runtimeConfig.js";
import {
  buildSessionClientSummary,
  buildSessionStateSummary,
  createAnonymousSessionState,
  createFetchSessionClient,
  createMockSessionClient
} from "./sessionClient.js";

export const AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION =
  "ae_web_session_bootstrap.v1";

export const AE_WEB_SESSION_BOOTSTRAP_PHASES = [
  "loading",
  "ready",
  "blocked",
  "failed"
];

export class SessionBootstrapError extends Error {
  constructor(message, { status = "SESSION_BOOTSTRAP_INVALID" } = {}) {
    super(message);
    this.name = "SessionBootstrapError";
    this.status = status;
  }
}

export async function bootstrapAuthenticatedSessionRuntime({
  runtimeConfig = {},
  sessionClient = null,
  sessionSnapshot = null,
  documents = [],
  fetchImpl,
  responseFactories = {}
} = {}) {
  const normalizedRuntimeConfig = normalizeRuntimeConfigInput(runtimeConfig);
  const resolvedSessionClient =
    sessionClient ||
    createSessionClientForRuntime({
      runtimeConfig: normalizedRuntimeConfig,
      sessionSnapshot,
      fetchImpl
    });

  let sessionState;
  let sessionReadErrorStatus = null;
  try {
    sessionState = await resolvedSessionClient.getCurrentSession();
  } catch (error) {
    sessionState = createAnonymousSessionState({
      reason: "session_bootstrap_failed"
    });
    sessionReadErrorStatus = safeErrorStatus(error);
  }

  const bootstrap = composeAuthenticatedSessionRuntime({
    runtimeConfig: normalizedRuntimeConfig,
    sessionState,
    sessionClient: resolvedSessionClient,
    documents,
    fetchImpl,
    responseFactories
  });

  if (sessionReadErrorStatus) {
    return {
      ...bootstrap,
      phase: "failed",
      session_read_error_status: sessionReadErrorStatus,
      metadata: {
        ...bootstrap.metadata,
        sessionReadFailed: true
      }
    };
  }
  return bootstrap;
}

export function composeAuthenticatedSessionRuntime({
  runtimeConfig = {},
  sessionState = null,
  sessionClient = null,
  documents = [],
  fetchImpl,
  responseFactories = {}
} = {}) {
  const normalizedRuntimeConfig = normalizeRuntimeConfigInput(runtimeConfig);
  const normalizedSessionState =
    sessionState || createAnonymousSessionState({ reason: "session_bootstrap_pending" });
  const resolvedSessionClient =
    sessionClient ||
    createSessionClientForRuntime({
      runtimeConfig: normalizedRuntimeConfig,
      fetchImpl
    });

  try {
    const runtime = createAuthenticatedAeWebRuntime({
      runtimeConfig: normalizedRuntimeConfig,
      sessionState: normalizedSessionState,
      sessionClient: resolvedSessionClient,
      documents,
      fetchImpl,
      responseFactories
    });
    return buildSessionBootstrapState({
      phase: "ready",
      runtime,
      requestedClientMode: normalizedRuntimeConfig.clientMode,
      activeClientMode: runtime.clientRegistry.clientMode,
      blockedReasons: []
    });
  } catch (error) {
    if (
      error instanceof AuthenticatedRuntimeError &&
      error.status === "AUTHENTICATED_RUNTIME_FETCH_BLOCKED"
    ) {
      const runtime = buildBlockedFetchRuntime({
        runtimeConfig: normalizedRuntimeConfig,
        sessionState: normalizedSessionState,
        sessionClient: resolvedSessionClient,
        documents,
        responseFactories
      });
      return buildSessionBootstrapState({
        phase: "blocked",
        runtime,
        requestedClientMode: normalizedRuntimeConfig.clientMode,
        activeClientMode: runtime.clientRegistry.clientMode,
        blockedReasons: error.blockedReasons
      });
    }
    throw error;
  }
}

export function buildSessionBootstrapSummary(bootstrap) {
  if (
    !bootstrap ||
    bootstrap.session_bootstrap_schema_version !==
      AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION
  ) {
    throw new SessionBootstrapError("Session bootstrap summary input is invalid.", {
      status: "SESSION_BOOTSTRAP_SUMMARY_INVALID"
    });
  }
  assertBootstrapPhase(bootstrap.phase);
  return {
    session_bootstrap_schema_version: bootstrap.session_bootstrap_schema_version,
    phase: bootstrap.phase,
    requested_client_mode: bootstrap.requested_client_mode,
    active_client_mode: bootstrap.active_client_mode,
    session_state: bootstrap.session_state,
    session_read_error_status: bootstrap.session_read_error_status,
    blocked_reasons: bootstrap.blocked_reasons,
    session_client: bootstrap.session_client,
    metadata: bootstrap.metadata
  };
}

function buildSessionBootstrapState({
  phase,
  runtime,
  requestedClientMode,
  activeClientMode,
  blockedReasons
}) {
  assertBootstrapPhase(phase);
  return {
    session_bootstrap_schema_version: AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION,
    phase,
    runtime,
    requested_client_mode: requestedClientMode,
    active_client_mode: activeClientMode,
    session_state: buildSessionStateSummary(runtime.sessionState),
    session_client: buildSessionClientSummary(runtime.sessionClient),
    session_read_error_status: null,
    blocked_reasons: [...blockedReasons],
    metadata: {
      rawTokenStored: false,
      serviceTokenStored: false,
      passwordStored: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false,
      browserPayloadAuthoritative: false,
      claimAuthoritativeWhenAuthenticated: true,
      sessionReadFailed: false
    }
  };
}

function buildBlockedFetchRuntime({
  runtimeConfig,
  sessionState,
  sessionClient,
  documents,
  responseFactories
}) {
  const fallbackRuntimeConfig = {
    ...runtimeConfig,
    clientMode: "mock"
  };
  const fallbackRuntime = createAuthenticatedAeWebRuntime({
    runtimeConfig: fallbackRuntimeConfig,
    sessionState,
    sessionClient,
    documents,
    responseFactories
  });
  return {
    ...fallbackRuntime,
    authenticated_runtime_schema_version: AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION,
    runtimeConfig,
    authBoundary: auditAuthenticatedRuntimeBoundary({
      clientMode: runtimeConfig.clientMode,
      fetchClientsEnabled: runtimeConfig.features.fetch_clients_enabled,
      sessionState: sessionState.status,
      credentialMode: runtimeConfig.clientMode === "fetch" ? "same-origin" : "none",
      ownerScopeSource:
        sessionState.status === "authenticated" ? "session-claims" : "mock-local",
      runtimeConfig: runtimeConfigForAuthAudit(runtimeConfig)
    }),
    clientRegistry: createAeWebClients({
      mode: "mock",
      documents,
      responseFactories
    }),
    metadata: {
      ...fallbackRuntime.metadata,
      blockedFetchFallbackClientMode: "mock"
    }
  };
}

function createSessionClientForRuntime({
  runtimeConfig,
  sessionSnapshot = null,
  fetchImpl
}) {
  if (runtimeConfig.clientMode === "fetch") {
    return createFetchSessionClient({
      baseUrl: runtimeConfig.aeBaseUrl,
      fetchImpl
    });
  }
  return createMockSessionClient({ sessionSnapshot });
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

function runtimeConfigForAuthAudit(runtimeConfig) {
  return {
    runtime_config_schema_version: runtimeConfig.runtime_config_schema_version,
    client_mode: runtimeConfig.clientMode,
    ae_base_url: runtimeConfig.aeBaseUrl,
    features: runtimeConfig.features
  };
}

function safeErrorStatus(error) {
  return typeof error?.status === "string" ? error.status : "SESSION_READ_FAILED";
}

function assertBootstrapPhase(phase) {
  if (!AE_WEB_SESSION_BOOTSTRAP_PHASES.includes(phase)) {
    throw new SessionBootstrapError("Unsupported session bootstrap phase.", {
      status: "SESSION_BOOTSTRAP_PHASE_UNSUPPORTED"
    });
  }
}
