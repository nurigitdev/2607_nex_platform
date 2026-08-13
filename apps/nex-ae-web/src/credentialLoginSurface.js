export const AE_WEB_CREDENTIAL_LOGIN_SURFACE_SCHEMA_VERSION =
  "ae_web_credential_login_surface.v1";

export const CREDENTIAL_LOGIN_ALLOWED_FIELDS = [
  "tenant_id",
  "employee_id",
  "login_identifier",
  "password",
  "requested_scopes",
  "scopes",
  "ttl_seconds"
];

const DEFAULT_REQUESTED_SCOPES = ["workspace:use"];
const DEFAULT_TTL_SECONDS = 3600;
const MAX_TTL_SECONDS = 86400;
const REQUIRED_TEXT_STATUSES = {
  tenant_id: "CREDENTIAL_LOGIN_TENANT_ID_REQUIRED",
  employee_id: "CREDENTIAL_LOGIN_EMPLOYEE_ID_REQUIRED",
  password: "CREDENTIAL_LOGIN_PASSWORD_REQUIRED"
};

export class CredentialLoginSurfaceError extends Error {
  constructor(message, { status = "CREDENTIAL_LOGIN_SURFACE_INVALID" } = {}) {
    super(message);
    this.name = "CredentialLoginSurfaceError";
    this.status = status;
  }
}

export function createCredentialLoginSurfaceState({
  tenantId = "tenant-local",
  employeeId = "",
  requestedScopes = DEFAULT_REQUESTED_SCOPES,
  ttlSeconds = DEFAULT_TTL_SECONDS,
  status = "READY_FOR_LOGIN",
  reason = "not_submitted",
  errorStatus = null
} = {}) {
  return {
    credential_login_surface_schema_version:
      AE_WEB_CREDENTIAL_LOGIN_SURFACE_SCHEMA_VERSION,
    tenantId: normalizeOptionalText(tenantId, "tenant_id") || "tenant-local",
    employeeId: normalizeOptionalText(employeeId, "employee_id") || "",
    requestedScopes: normalizeScopes(requestedScopes),
    ttlSeconds: normalizeTtl(ttlSeconds),
    status,
    reason,
    errorStatus,
    metadata: safeCredentialLoginMetadata()
  };
}

export function buildCredentialLoginRequest({
  tenantId,
  employeeId,
  loginIdentifier,
  password,
  requestedScopes = DEFAULT_REQUESTED_SCOPES,
  scopes,
  ttlSeconds = DEFAULT_TTL_SECONDS
} = {}) {
  const normalizedTenantId = requiredText(tenantId, "tenant_id");
  const normalizedEmployeeId = requiredText(
    employeeId || loginIdentifier,
    "employee_id"
  );
  const normalizedPassword = requiredText(password, "password");
  if (scopes !== undefined && requestedScopes !== DEFAULT_REQUESTED_SCOPES) {
    throw new CredentialLoginSurfaceError(
      "Credential login request must use either scopes or requestedScopes.",
      { status: "CREDENTIAL_LOGIN_SCOPE_CONFLICT" }
    );
  }

  return {
    tenant_id: normalizedTenantId,
    employee_id: normalizedEmployeeId,
    password: normalizedPassword,
    requested_scopes: normalizeScopes(scopes || requestedScopes),
    ttl_seconds: normalizeTtl(ttlSeconds)
  };
}

export function buildCredentialLoginRequestFromForm({
  tenantInput,
  employeeInput,
  passwordInput,
  requestedScopes = DEFAULT_REQUESTED_SCOPES,
  ttlSeconds = DEFAULT_TTL_SECONDS
}) {
  return buildCredentialLoginRequest({
    tenantId: tenantInput?.value,
    employeeId: employeeInput?.value,
    password: passwordInput?.value,
    requestedScopes,
    ttlSeconds
  });
}

export function buildCredentialLoginSurfaceSummary(surfaceState) {
  if (
    !surfaceState ||
    surfaceState.credential_login_surface_schema_version !==
      AE_WEB_CREDENTIAL_LOGIN_SURFACE_SCHEMA_VERSION
  ) {
    throw new CredentialLoginSurfaceError("Credential login summary input is invalid.", {
      status: "CREDENTIAL_LOGIN_SUMMARY_INVALID"
    });
  }
  return {
    credential_login_surface_schema_version:
      surfaceState.credential_login_surface_schema_version,
    status: surfaceState.status,
    reason: surfaceState.reason,
    tenant_id: surfaceState.tenantId,
    employee_id_present: Boolean(surfaceState.employeeId),
    requested_scope_count: surfaceState.requestedScopes.length,
    ttl_seconds: surfaceState.ttlSeconds,
    error_status: surfaceState.errorStatus,
    metadata: surfaceState.metadata
  };
}

export function assertCredentialLoginRequestShape(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new CredentialLoginSurfaceError(
      "Credential login request must be an object.",
      { status: "CREDENTIAL_LOGIN_REQUEST_INVALID" }
    );
  }
  const unsupported = Object.keys(payload).find(
    key => !CREDENTIAL_LOGIN_ALLOWED_FIELDS.includes(key)
  );
  if (unsupported) {
    throw new CredentialLoginSurfaceError(
      "Credential login request contains an unsupported field.",
      { status: "CREDENTIAL_LOGIN_FIELD_UNSUPPORTED" }
    );
  }
}

function requiredText(value, fieldName) {
  const normalized = normalizeOptionalText(value, fieldName);
  if (!normalized) {
    throw new CredentialLoginSurfaceError(`${fieldName} is required.`, {
      status:
        REQUIRED_TEXT_STATUSES[fieldName] ||
        `CREDENTIAL_LOGIN_${fieldName.toUpperCase()}_REQUIRED`
    });
  }
  return normalized;
}

function normalizeOptionalText(value, fieldName) {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") {
    throw new CredentialLoginSurfaceError(`${fieldName} must be text.`, {
      status: "CREDENTIAL_LOGIN_TEXT_INVALID"
    });
  }
  return value.trim();
}

function normalizeScopes(value) {
  if (!Array.isArray(value) || value.length === 0) {
    throw new CredentialLoginSurfaceError(
      "Credential login scopes must be a non-empty list.",
      { status: "CREDENTIAL_LOGIN_SCOPES_INVALID" }
    );
  }
  const normalized = value.map(scope => {
    if (typeof scope !== "string" || !scope.trim()) {
      throw new CredentialLoginSurfaceError(
        "Credential login scopes must be non-empty strings.",
        { status: "CREDENTIAL_LOGIN_SCOPES_INVALID" }
      );
    }
    return scope.trim();
  });
  return [...normalized];
}

function normalizeTtl(value) {
  if (!Number.isInteger(value) || value <= 0 || value > MAX_TTL_SECONDS) {
    throw new CredentialLoginSurfaceError(
      "Credential login ttlSeconds must be a positive bounded integer.",
      { status: "CREDENTIAL_LOGIN_TTL_INVALID" }
    );
  }
  return value;
}

function safeCredentialLoginMetadata() {
  return {
    rawPasswordStored: false,
    passwordRendered: false,
    passwordIncludedInSummary: false,
    serviceTokenIncluded: false,
    databaseEndpointIncluded: false,
    providerEndpointIncluded: false
  };
}
