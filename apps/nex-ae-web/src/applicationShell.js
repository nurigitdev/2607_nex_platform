export const AE_WEB_APPLICATION_SHELL_SCHEMA_VERSION =
  "ae_web_application_shell.p8_s42a.v1";

export const AE_WEB_DEFAULT_VIEW = "workspace";
export const AE_WEB_AUTHENTICATED_VIEWS = Object.freeze([
  "workspace",
  "approvals",
  "upload",
  "documents",
  "retrieval",
  "artifacts",
  "operations"
]);

const OPERATIONS_ROLES = new Set(["admin", "operator"]);

export function isAuthenticatedSession(sessionState) {
  return sessionState?.status === "authenticated";
}

export function canAccessOperations(sessionState) {
  if (!isAuthenticatedSession(sessionState)) return false;
  return (sessionState.roles || []).some(role =>
    OPERATIONS_ROLES.has(String(role).trim().toLowerCase())
  );
}

export function allowedApplicationViews(sessionState) {
  if (!isAuthenticatedSession(sessionState)) return [];
  return AE_WEB_AUTHENTICATED_VIEWS.filter(
    view => view !== "operations" || canAccessOperations(sessionState)
  );
}

export function viewFromLocationHash(hash) {
  const value = String(hash || "").replace(/^#/, "").trim().toLowerCase();
  return AE_WEB_AUTHENTICATED_VIEWS.includes(value) ? value : null;
}

export function resolveApplicationShell({
  sessionState,
  requestedView = AE_WEB_DEFAULT_VIEW
} = {}) {
  const authenticated = isAuthenticatedSession(sessionState);
  const allowedViews = allowedApplicationViews(sessionState);
  const normalizedRequestedView = AE_WEB_AUTHENTICATED_VIEWS.includes(requestedView)
    ? requestedView
    : AE_WEB_DEFAULT_VIEW;
  const activeView = authenticated && allowedViews.includes(normalizedRequestedView)
    ? normalizedRequestedView
    : authenticated
      ? AE_WEB_DEFAULT_VIEW
      : null;

  return {
    application_shell_schema_version: AE_WEB_APPLICATION_SHELL_SCHEMA_VERSION,
    authenticated,
    authenticationVisible: !authenticated,
    applicationVisible: authenticated,
    activeView,
    allowedViews,
    operationsVisible: canAccessOperations(sessionState),
    sessionStatus: sessionState?.status || "anonymous"
  };
}

export function buildApplicationShellSummary(shell) {
  return {
    application_shell_schema_version: shell.application_shell_schema_version,
    authenticated: shell.authenticated,
    active_view: shell.activeView,
    allowed_view_count: shell.allowedViews.length,
    operations_visible: shell.operationsVisible,
    session_status: shell.sessionStatus
  };
}
