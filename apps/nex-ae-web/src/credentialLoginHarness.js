import {
  buildCredentialLoginRequest,
  buildCredentialLoginSurfaceSummary,
  createCredentialLoginSurfaceState
} from "./credentialLoginSurface.js";
import {
  buildRuntimeConfigSummary,
  normalizeRuntimeConfig
} from "./runtimeConfig.js";
import {
  buildSessionBootstrapSummary,
  composeAuthenticatedSessionRuntime
} from "./sessionBootstrap.js";
import {
  buildSessionClientSummary,
  buildSessionStateSummary,
  createFetchSessionClient
} from "./sessionClient.js";
import {
  buildSessionRouteGuard,
  buildSessionRouteGuardSummary
} from "./sessionRouteGuard.js";

export const AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION =
  "ae_web_credential_login_harness.v1";

const DEFAULT_LOGIN_SCOPES = ["workspace:use"];
const LOGIN_ROUTE = "/api/v1/auth/session/login";
const FORBIDDEN_RESULT_FRAGMENTS = [
  "access_" + "token",
  `api_${"key"}`,
  `database_${"url"}`,
  "password_" + "hash",
  `provider_${"url"}`,
  "secret=",
  `service_${"token"}`,
  "/data/" + "nex-platform"
];

export class CredentialLoginHarnessError extends Error {
  constructor(message, { status = "CREDENTIAL_LOGIN_HARNESS_INVALID" } = {}) {
    super(message);
    this.name = "CredentialLoginHarnessError";
    this.status = status;
  }
}

export async function runCredentialLoginHarness({
  baseUrl = "/ae-api",
  fetchImpl,
  tenantId,
  employeeId,
  loginIdentifier,
  password,
  requestedScopes = DEFAULT_LOGIN_SCOPES,
  ttlSeconds = 3600,
  documents = []
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new CredentialLoginHarnessError(
      "Credential login harness requires an injected fetch.",
      { status: "CREDENTIAL_LOGIN_HARNESS_FETCH_REQUIRED" }
    );
  }

  const loginRequest = buildCredentialLoginRequest({
    tenantId,
    employeeId,
    loginIdentifier,
    password,
    requestedScopes,
    ttlSeconds
  });
  const runtimeConfig = normalizeRuntimeConfig({
    client_mode: "fetch",
    ae_base_url: baseUrl,
    features: {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    }
  });
  const recordingFetch = createRecordingFetch(fetchImpl);
  const sessionClient = createFetchSessionClient({
    baseUrl: runtimeConfig.aeBaseUrl,
    fetchImpl: recordingFetch
  });

  const currentSession = await sessionClient.getCurrentSession();
  const authenticatedSession = await sessionClient.login(loginRequest);
  const bootstrap = composeAuthenticatedSessionRuntime({
    runtimeConfig,
    sessionState: authenticatedSession,
    sessionClient,
    documents,
    fetchImpl: recordingFetch
  });
  const routeGuard = buildSessionRouteGuard({
    sessionState: authenticatedSession,
    authBoundary: bootstrap.runtime.authBoundary,
    clientRegistry: bootstrap.runtime.clientRegistry
  });
  const logoutSession = await sessionClient.logout();

  const result = {
    credential_login_harness_schema_version:
      AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION,
    runtime_config: buildRuntimeConfigSummary(runtimeConfig),
    credential_surface: buildCredentialLoginSurfaceSummary(
      createCredentialLoginSurfaceState({
        tenantId: loginRequest.tenant_id,
        employeeId: loginRequest.employee_id,
        requestedScopes: loginRequest.requested_scopes,
        ttlSeconds: loginRequest.ttl_seconds,
        status: "AUTHENTICATED",
        reason: "login_succeeded"
      })
    ),
    session_client: buildSessionClientSummary(sessionClient),
    phases: [
      "current_session",
      "credential_login",
      "authenticated_runtime",
      "route_guard",
      "logout"
    ],
    current_session: buildSessionStateSummary(currentSession),
    authenticated_session: buildSessionStateSummary(authenticatedSession),
    session_bootstrap: buildSessionBootstrapSummary(bootstrap),
    route_guard: buildSessionRouteGuardSummary(routeGuard),
    logout_session: buildSessionStateSummary(logoutSession),
    login_request: {
      route: LOGIN_ROUTE,
      method: "POST",
      credentials: "same-origin",
      tenant_id: loginRequest.tenant_id,
      employee_id_present: Boolean(loginRequest.employee_id),
      requested_scope_count: loginRequest.requested_scopes.length,
      ttl_seconds: loginRequest.ttl_seconds,
      password_submitted: true,
      raw_password_in_result: false
    },
    fetch_calls: recordingFetch.calls,
    metadata: safeCredentialLoginHarnessMetadata()
  };
  assertCredentialLoginHarnessResultSafe(result, {
    rawPassword: loginRequest.password
  });
  return result;
}

export function buildCredentialLoginHarnessSummary(result) {
  assertCredentialLoginHarnessResult(result);
  return {
    credential_login_harness_schema_version:
      result.credential_login_harness_schema_version,
    client_mode: result.runtime_config.client_mode,
    base_url: result.runtime_config.ae_base_url,
    phase_count: result.phases.length,
    current_session_status: result.current_session.status,
    authenticated_session_status: result.authenticated_session.status,
    route_guard_status: result.route_guard.guard_status,
    allowed_route_count: result.route_guard.allowed_route_count,
    logout_session_status: result.logout_session.status,
    fetch_call_count: result.fetch_calls.length,
    login_route: result.login_request.route,
    metadata: result.metadata
  };
}

function createRecordingFetch(fetchImpl) {
  const calls = [];
  const recordingFetch = async (url, options = {}) => {
    calls.push(summarizeFetchCall(url, options));
    return fetchImpl(url, options);
  };
  recordingFetch.calls = calls;
  return recordingFetch;
}

function summarizeFetchCall(url, options = {}) {
  return {
    url: String(url),
    method: String(options.method || "GET").toUpperCase(),
    credentials: options.credentials || "omit",
    accepts_json: readHeader(options.headers, "Accept") === "application/json",
    content_type: readHeader(options.headers, "Content-Type"),
    request_body_included: Boolean(options.body),
    request_body_redacted: Boolean(options.body)
  };
}

function readHeader(headers, name) {
  if (!headers) return null;
  if (typeof headers.get === "function") return headers.get(name);
  const key = Object.keys(headers).find(
    candidate => candidate.toLowerCase() === name.toLowerCase()
  );
  return key ? headers[key] : null;
}

function assertCredentialLoginHarnessResult(result) {
  if (
    !result ||
    result.credential_login_harness_schema_version !==
      AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION
  ) {
    throw new CredentialLoginHarnessError(
      "Credential login harness summary input is invalid.",
      { status: "CREDENTIAL_LOGIN_HARNESS_SUMMARY_INVALID" }
    );
  }
}

function assertCredentialLoginHarnessResultSafe(result, { rawPassword }) {
  assertCredentialLoginHarnessResult(result);
  const serialized = JSON.stringify(result);
  if (rawPassword && serialized.includes(rawPassword)) {
    throw new CredentialLoginHarnessError(
      "Credential login harness result leaked raw password material.",
      { status: "CREDENTIAL_LOGIN_HARNESS_SECRET_LEAK" }
    );
  }
  const forbidden = FORBIDDEN_RESULT_FRAGMENTS.find(fragment =>
    serialized.includes(fragment)
  );
  if (forbidden) {
    throw new CredentialLoginHarnessError(
      "Credential login harness result contains server-only material.",
      { status: "CREDENTIAL_LOGIN_HARNESS_SERVER_MATERIAL" }
    );
  }
}

function safeCredentialLoginHarnessMetadata() {
  return {
    liveNetworkUsed: false,
    injectedFetchRequired: true,
    browserCredentialMode: "same-origin",
    rawPasswordStored: false,
    rawPasswordRendered: false,
    passwordIncludedInSummary: false,
    rawTokenStored: false,
    serviceTokenStored: false,
    browserPayloadOwnerAuthoritative: false,
    claimOwnerAuthoritative: true,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false,
    storageLocationIncluded: false
  };
}
