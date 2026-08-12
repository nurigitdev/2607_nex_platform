export const AE_WEB_SESSION_STATE_SCHEMA_VERSION = "ae_web_session_state.v1";
export const AE_WEB_SESSION_CLIENT_SCHEMA_VERSION = "ae_web_session_client.v1";

export const AE_WEB_SESSION_STATUSES = ["anonymous", "authenticated", "expired"];

const OA_BROWSER_SESSION_SCHEMA_VERSION = "oa_browser_session.v1";
const RAW_TOKEN_FIELD = `raw_${"token"}_included`;
const SERVICE_TOKEN_FIELD = `service_${"token"}_included`;
const PASSWORD_FIELD = "password_included";
const ALLOWED_SERVER_METADATA_FIELDS = new Set([
  RAW_TOKEN_FIELD,
  SERVICE_TOKEN_FIELD,
  PASSWORD_FIELD,
  "browser_payload_owner_authoritative",
  "claim_owner_authoritative"
]);
const ALLOWED_BROWSER_SESSION_ROOT_FIELDS = new Set(["token_use"]);

const FORBIDDEN_SESSION_KEY_PARTS = [
  "access",
  `api_${"key"}`,
  "authorization",
  "credential",
  `database_${"url"}`,
  "passwd",
  "password",
  `provider_${"url"}`,
  "secret",
  `service_${"token"}`,
  `token`
];

export class SessionClientError extends Error {
  constructor(message, { status = "SESSION_CLIENT_INVALID", retryable = false } = {}) {
    super(message);
    this.name = "SessionClientError";
    this.status = status;
    this.retryable = retryable;
  }
}

export function createAnonymousSessionState({
  reason = "not_authenticated"
} = {}) {
  return {
    session_state_schema_version: AE_WEB_SESSION_STATE_SCHEMA_VERSION,
    status: "anonymous",
    sessionId: null,
    tenantRef: null,
    subjectRef: null,
    scopes: [],
    roles: [],
    reason,
    metadata: safeSessionMetadata()
  };
}

export function createExpiredSessionState({
  sessionId = null,
  reason = "expired"
} = {}) {
  return {
    ...createAnonymousSessionState({ reason }),
    status: "expired",
    sessionId
  };
}

export function normalizeBrowserSessionSnapshot(snapshot) {
  assertSessionPayloadSafe(snapshot);
  if (!isObject(snapshot)) {
    throw new SessionClientError("Browser session snapshot must be an object.", {
      status: "SESSION_SNAPSHOT_INVALID"
    });
  }
  if (snapshot.browser_session_schema_version !== OA_BROWSER_SESSION_SCHEMA_VERSION) {
    throw new SessionClientError("Unsupported browser session schema version.", {
      status: "SESSION_SCHEMA_UNSUPPORTED"
    });
  }
  if (snapshot.token_use !== "user") {
    throw new SessionClientError("Browser session must be a user session.", {
      status: "SESSION_TOKEN_USE_INVALID"
    });
  }
  if (snapshot.audience !== "nex-ae-api") {
    throw new SessionClientError("Browser session audience is invalid.", {
      status: "SESSION_AUDIENCE_INVALID"
    });
  }
  assertSafeServerSessionMetadata(snapshot.metadata);

  const tenantRef = normalizeRef(snapshot.tenant_ref, {
    expectedType: "oa.tenant",
    status: "SESSION_TENANT_REF_INVALID"
  });
  const subjectRef = normalizeRef(snapshot.subject_ref, {
    expectedType: "oa.user",
    status: "SESSION_SUBJECT_REF_INVALID"
  });
  const scopes = normalizeStringList(snapshot.scopes, {
    status: "SESSION_SCOPES_INVALID"
  });
  const roles = normalizeStringList(snapshot.roles || [], {
    status: "SESSION_ROLES_INVALID"
  });

  if (snapshot.status === "ACTIVE") {
    return {
      session_state_schema_version: AE_WEB_SESSION_STATE_SCHEMA_VERSION,
      status: "authenticated",
      sessionId: requiredText(snapshot.session_id, "SESSION_ID_INVALID"),
      tenantRef,
      subjectRef,
      scopes,
      roles,
      reason: null,
      issuedAt: requiredText(snapshot.issued_at, "SESSION_ISSUED_AT_INVALID"),
      expiresAt: requiredText(snapshot.expires_at, "SESSION_EXPIRES_AT_INVALID"),
      metadata: safeSessionMetadata()
    };
  }
  if (snapshot.status === "EXPIRED" || snapshot.status === "REVOKED") {
    return createExpiredSessionState({
      sessionId: requiredText(snapshot.session_id, "SESSION_ID_INVALID"),
      reason: snapshot.status.toLowerCase()
    });
  }
  throw new SessionClientError("Unsupported browser session status.", {
    status: "SESSION_STATUS_UNSUPPORTED"
  });
}

export function buildSessionStateSummary(sessionState) {
  if (
    !isObject(sessionState) ||
    sessionState.session_state_schema_version !== AE_WEB_SESSION_STATE_SCHEMA_VERSION
  ) {
    throw new SessionClientError("Session state summary input is invalid.", {
      status: "SESSION_STATE_SUMMARY_INVALID"
    });
  }

  return {
    session_state_schema_version: sessionState.session_state_schema_version,
    status: sessionState.status,
    session_id_present: Boolean(sessionState.sessionId),
    tenant_ref: sessionState.tenantRef,
    subject_ref: sessionState.subjectRef,
    scope_count: sessionState.scopes.length,
    role_count: sessionState.roles.length,
    reason: sessionState.reason,
    metadata: sessionState.metadata
  };
}

export function createMockSessionClient({
  sessionSnapshot = null
} = {}) {
  return {
    session_client_schema_version: AE_WEB_SESSION_CLIENT_SCHEMA_VERSION,
    clientMode: "mock",
    async getCurrentSession() {
      return sessionSnapshot
        ? normalizeBrowserSessionSnapshot(sessionSnapshot)
        : createAnonymousSessionState();
    },
    async login() {
      if (!sessionSnapshot) {
        throw new SessionClientError("Mock login session snapshot is unavailable.", {
          status: "MOCK_LOGIN_UNAVAILABLE",
          retryable: false
        });
      }
      return normalizeBrowserSessionSnapshot(sessionSnapshot);
    },
    async logout() {
      return createAnonymousSessionState({ reason: "logout" });
    },
    metadata: safeClientMetadata()
  };
}

export function createFetchSessionClient({
  baseUrl = "",
  fetchImpl = globalThis.fetch
} = {}) {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  return {
    session_client_schema_version: AE_WEB_SESSION_CLIENT_SCHEMA_VERSION,
    clientMode: "fetch",
    async getCurrentSession() {
      return fetchSessionSnapshot({
        fetchImpl,
        url: `${normalizedBaseUrl}/api/v1/auth/session`,
        options: {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "same-origin"
        },
        allowAnonymous: true
      });
    },
    async login(loginHint = {}) {
      assertSessionPayloadSafe(loginHint);
      return fetchSessionSnapshot({
        fetchImpl,
        url: `${normalizedBaseUrl}/api/v1/auth/session/login`,
        options: {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(loginHint)
        }
      });
    },
    async logout() {
      await fetchSessionSnapshot({
        fetchImpl,
        url: `${normalizedBaseUrl}/api/v1/auth/session/logout`,
        options: {
          method: "POST",
          headers: { Accept: "application/json" },
          credentials: "same-origin"
        },
        allowAnonymous: true
      });
      return createAnonymousSessionState({ reason: "logout" });
    },
    metadata: safeClientMetadata()
  };
}

export function buildSessionClientSummary(client) {
  if (
    !isObject(client) ||
    client.session_client_schema_version !== AE_WEB_SESSION_CLIENT_SCHEMA_VERSION
  ) {
    throw new SessionClientError("Session client summary input is invalid.", {
      status: "SESSION_CLIENT_SUMMARY_INVALID"
    });
  }
  return {
    session_client_schema_version: client.session_client_schema_version,
    client_mode: client.clientMode,
    metadata: client.metadata
  };
}

export function assertSessionPayloadSafe(value, path = "session") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertSessionPayloadSafe(item, `${path}[${index}]`));
    return;
  }
  if (!isObject(value)) return;
  for (const [key, nestedValue] of Object.entries(value)) {
    const normalizedKey = key.toLowerCase();
    if (
      !(path === "session" && ALLOWED_BROWSER_SESSION_ROOT_FIELDS.has(key)) &&
      !(path === "session.metadata" && ALLOWED_SERVER_METADATA_FIELDS.has(key)) &&
      FORBIDDEN_SESSION_KEY_PARTS.some(part => normalizedKey.includes(part))
    ) {
      throw new SessionClientError("Session payload contains a forbidden field.", {
        status: "SESSION_SECRET_FIELD",
        fieldPath: `${path}.${key}`
      });
    }
    assertSessionPayloadSafe(nestedValue, `${path}.${key}`);
  }
}

async function fetchSessionSnapshot({
  fetchImpl,
  url,
  options,
  allowAnonymous = false
}) {
  if (typeof fetchImpl !== "function") {
    throw new SessionClientError("fetch is required for fetch session client.", {
      status: "FETCH_UNAVAILABLE",
      retryable: true
    });
  }
  let response;
  try {
    response = await fetchImpl(url, options);
  } catch {
    throw new SessionClientError("Session request failed.", {
      status: "NETWORK_ERROR",
      retryable: true
    });
  }
  if (response.status === 401 && allowAnonymous) {
    return createAnonymousSessionState();
  }
  if (!response.ok) {
    throw new SessionClientError("Session request returned an error.", {
      status: `HTTP_${response.status}`,
      retryable: response.status >= 500
    });
  }
  return normalizeBrowserSessionSnapshot(await response.json());
}

function assertSafeServerSessionMetadata(metadata) {
  if (!isObject(metadata)) {
    throw new SessionClientError("Browser session metadata is invalid.", {
      status: "SESSION_METADATA_INVALID"
    });
  }
  if (
    metadata[RAW_TOKEN_FIELD] !== false ||
    metadata[SERVICE_TOKEN_FIELD] !== false ||
    metadata[PASSWORD_FIELD] !== false ||
    metadata.browser_payload_owner_authoritative !== false ||
    metadata.claim_owner_authoritative !== true
  ) {
    throw new SessionClientError("Browser session metadata is not browser safe.", {
      status: "SESSION_METADATA_UNSAFE"
    });
  }
}

function safeSessionMetadata() {
  return {
    rawTokenIncluded: false,
    serviceTokenIncluded: false,
    passwordIncluded: false,
    browserPayloadOwnerAuthoritative: false,
    claimOwnerAuthoritative: true
  };
}

function safeClientMetadata() {
  return {
    rawTokenStored: false,
    serviceTokenStored: false,
    passwordStored: false,
    browserCredentialMode: "same-origin"
  };
}

function normalizeRef(value, { expectedType, status }) {
  if (!isObject(value) || value.type !== expectedType) {
    throw new SessionClientError("Browser session reference is invalid.", {
      status
    });
  }
  return {
    type: expectedType,
    id: requiredText(value.id, status)
  };
}

function normalizeStringList(value, { status }) {
  if (!Array.isArray(value) || !value.every(item => typeof item === "string")) {
    throw new SessionClientError("Browser session list is invalid.", {
      status
    });
  }
  return [...value];
}

function requiredText(value, status) {
  if (typeof value !== "string" || !value.trim()) {
    throw new SessionClientError("Browser session field is required.", {
      status
    });
  }
  return value.trim();
}

function normalizeBaseUrl(baseUrl) {
  if (baseUrl == null || baseUrl === "") return "";
  if (typeof baseUrl !== "string") {
    throw new SessionClientError("baseUrl must be a string.", {
      status: "BASE_URL_INVALID"
    });
  }
  return baseUrl.replace(/\/+$/, "");
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
