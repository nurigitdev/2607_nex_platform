export const AE_WEB_AUTH_BOUNDARY_SCHEMA_VERSION = "ae_web_auth_boundary.v1";

export const AE_WEB_SESSION_STATES = ["anonymous", "authenticated", "expired"];
export const AE_WEB_BROWSER_CREDENTIAL_MODES = ["none", "same-origin"];
export const AE_WEB_OWNER_SCOPE_SOURCES = ["mock-local", "session-claims"];

const FORBIDDEN_BROWSER_RUNTIME_KEY_PARTS = [
  `api_${"key"}`,
  "authorization",
  "credential",
  `database_${"url"}`,
  "passwd",
  "password",
  `provider_${"url"}`,
  "raw_prompt",
  "raw_source",
  "secret",
  `service_${"token"}`,
  "source_storage_path",
  "storage_path",
  "storage_uri",
  "token"
];

export class AuthBoundaryError extends Error {
  constructor(message, { status = "AUTH_BOUNDARY_INVALID" } = {}) {
    super(message);
    this.name = "AuthBoundaryError";
    this.status = status;
  }
}

export function auditAuthenticatedRuntimeBoundary({
  clientMode = "mock",
  fetchClientsEnabled = false,
  sessionState = "anonymous",
  credentialMode,
  ownerScopeSource,
  runtimeConfig = {}
} = {}) {
  assertBrowserRuntimeSafe(runtimeConfig);
  const normalizedSessionState = normalizeSessionState(sessionState);
  const requestedFetchMode = clientMode === "fetch";
  const normalizedCredentialMode = normalizeCredentialMode(
    credentialMode ?? (requestedFetchMode ? "same-origin" : "none")
  );
  const normalizedOwnerScopeSource = normalizeOwnerScopeSource(
    ownerScopeSource ??
      (normalizedSessionState === "authenticated" ? "session-claims" : "mock-local")
  );

  const fetchModeAllowed =
    requestedFetchMode &&
    fetchClientsEnabled === true &&
    normalizedSessionState === "authenticated" &&
    normalizedCredentialMode === "same-origin" &&
    normalizedOwnerScopeSource === "session-claims";
  const blockedReasons = [];
  if (requestedFetchMode && fetchClientsEnabled !== true) {
    blockedReasons.push("fetch_clients_feature_disabled");
  }
  if (requestedFetchMode && normalizedSessionState !== "authenticated") {
    blockedReasons.push("browser_session_not_authenticated");
  }
  if (requestedFetchMode && normalizedCredentialMode !== "same-origin") {
    blockedReasons.push("browser_credentials_not_same_origin");
  }
  if (requestedFetchMode && normalizedOwnerScopeSource !== "session-claims") {
    blockedReasons.push("owner_scope_not_claim_derived");
  }

  return {
    auth_boundary_schema_version: AE_WEB_AUTH_BOUNDARY_SCHEMA_VERSION,
    browser_principal: {
      session_state: normalizedSessionState,
      token_use: normalizedSessionState === "authenticated" ? "user" : "none",
      serviceTokenIncluded: false
    },
    owner_scope: {
      source: normalizedOwnerScopeSource,
      browserPayloadAuthoritative: false,
      claimAuthoritative: normalizedOwnerScopeSource === "session-claims"
    },
    fetch_mode: {
      requested: requestedFetchMode,
      allowed: fetchModeAllowed,
      blocked_reasons: blockedReasons
    },
    backend_boundary: {
      browser_calls: "nex-ae-api-only",
      direct_cx_calls_allowed: false,
      direct_mo_calls_allowed: false,
      direct_database_calls_allowed: false
    },
    credential_boundary: {
      browserCredentialMode: normalizedCredentialMode,
      serviceTokenIncluded: false,
      providerSecretIncluded: false,
      databaseUrlIncluded: false,
      storagePathIncluded: false,
      rawSourceIncluded: false
    }
  };
}

export function buildAuthBoundarySummary(boundary) {
  if (
    !boundary ||
    boundary.auth_boundary_schema_version !== AE_WEB_AUTH_BOUNDARY_SCHEMA_VERSION
  ) {
    throw new AuthBoundaryError("Auth boundary summary input is invalid.", {
      status: "AUTH_BOUNDARY_SUMMARY_INVALID"
    });
  }

  return {
    auth_boundary_schema_version: boundary.auth_boundary_schema_version,
    session_state: boundary.browser_principal.session_state,
    owner_scope_source: boundary.owner_scope.source,
    fetch_mode_requested: boundary.fetch_mode.requested,
    fetch_mode_allowed: boundary.fetch_mode.allowed,
    blocked_reasons: boundary.fetch_mode.blocked_reasons,
    browser_calls: boundary.backend_boundary.browser_calls,
    metadata: boundary.credential_boundary
  };
}

export function assertBrowserRuntimeSafe(value, path = "runtime_config") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertBrowserRuntimeSafe(item, `${path}[${index}]`));
    return;
  }
  if (!isObject(value)) return;

  for (const [key, nestedValue] of Object.entries(value)) {
    const normalizedKey = key.toLowerCase();
    if (FORBIDDEN_BROWSER_RUNTIME_KEY_PARTS.some(part => normalizedKey.includes(part))) {
      throw new AuthBoundaryError("Browser runtime config contains a forbidden field.", {
        status: "BROWSER_RUNTIME_SECRET_FIELD",
        fieldPath: `${path}.${key}`
      });
    }
    assertBrowserRuntimeSafe(nestedValue, `${path}.${key}`);
  }
}

function normalizeSessionState(sessionState) {
  if (!AE_WEB_SESSION_STATES.includes(sessionState)) {
    throw new AuthBoundaryError("Unsupported browser session state.", {
      status: "SESSION_STATE_UNSUPPORTED"
    });
  }
  return sessionState;
}

function normalizeCredentialMode(credentialMode) {
  if (!AE_WEB_BROWSER_CREDENTIAL_MODES.includes(credentialMode)) {
    throw new AuthBoundaryError("Unsupported browser credential mode.", {
      status: "BROWSER_CREDENTIAL_MODE_UNSUPPORTED"
    });
  }
  return credentialMode;
}

function normalizeOwnerScopeSource(ownerScopeSource) {
  if (!AE_WEB_OWNER_SCOPE_SOURCES.includes(ownerScopeSource)) {
    throw new AuthBoundaryError("Unsupported owner-scope source.", {
      status: "OWNER_SCOPE_SOURCE_UNSUPPORTED"
    });
  }
  return ownerScopeSource;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
