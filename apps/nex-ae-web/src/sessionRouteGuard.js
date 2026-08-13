import {
  buildAuthBoundarySummary
} from "./authBoundary.js";
import {
  buildClientRegistrySummary
} from "./clientRegistry.js";
import {
  buildSessionStateSummary
} from "./sessionClient.js";

export const AE_WEB_SESSION_ROUTE_GUARD_SCHEMA_VERSION =
  "ae_web_session_route_guard.v1";

export const AE_WEB_PROTECTED_ROUTE_IDS = [
  "auth_session",
  "document_detail",
  "upload_handoff",
  "retrieval_context"
];

const PROTECTED_ROUTE_TEMPLATES = {
  auth_session: "/api/v1/auth/session",
  document_detail: "/api/v1/documents/{document_id}",
  upload_handoff: "/api/v1/uploads",
  retrieval_context: "/api/v1/retrieval/contexts"
};

export class SessionRouteGuardError extends Error {
  constructor(message, { status = "SESSION_ROUTE_GUARD_INVALID" } = {}) {
    super(message);
    this.name = "SessionRouteGuardError";
    this.status = status;
  }
}

export function buildSessionRouteGuard({
  sessionState,
  authBoundary,
  clientRegistry
} = {}) {
  const session = buildSessionStateSummary(sessionState);
  const auth = buildAuthBoundarySummary(authBoundary);
  const registry = buildClientRegistrySummary(clientRegistry);
  const guardStatus = routeGuardStatus({
    fetchModeRequested: auth.fetch_mode_requested,
    fetchModeAllowed: auth.fetch_mode_allowed,
    clientMode: registry.client_mode
  });
  const ownerScope = ownerScopeFromSessionState(sessionState);

  return {
    session_route_guard_schema_version:
      AE_WEB_SESSION_ROUTE_GUARD_SCHEMA_VERSION,
    guard_status: guardStatus,
    client_mode: registry.client_mode,
    session_state: session.status,
    session_id_present: session.session_id_present,
    owner_scope_source: auth.owner_scope_source,
    owner_scope: ownerScope
      ? {
          tenant_ref: { type: "oa.tenant", id: ownerScope.tenantId },
          owner_subject_ref: { type: "oa.user", id: ownerScope.ownerUserId }
        }
      : null,
    protected_routes: AE_WEB_PROTECTED_ROUTE_IDS.map(routeId => ({
      route_id: routeId,
      route_template: PROTECTED_ROUTE_TEMPLATES[routeId],
      client_mode: routeId === "auth_session" ? "session-client" : registry.client_mode,
      allowed: guardStatus !== "blocked",
      owner_scope_authority:
        session.status === "authenticated" ? "session-claims" : "mock-local"
    })),
    blocked_reasons: [...auth.blocked_reasons],
    metadata: {
      browserCredentialMode: auth.metadata.browserCredentialMode,
      serviceTokenIncluded: false,
      rawPasswordStored: false,
      routeGuardUsesSessionClaims: session.status === "authenticated",
      browserPayloadOwnerAuthoritative: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false
    }
  };
}

export function buildSessionRouteGuardSummary(routeGuard) {
  if (
    !routeGuard ||
    routeGuard.session_route_guard_schema_version !==
      AE_WEB_SESSION_ROUTE_GUARD_SCHEMA_VERSION
  ) {
    throw new SessionRouteGuardError("Session route guard summary input is invalid.", {
      status: "SESSION_ROUTE_GUARD_SUMMARY_INVALID"
    });
  }
  return {
    session_route_guard_schema_version:
      routeGuard.session_route_guard_schema_version,
    guard_status: routeGuard.guard_status,
    client_mode: routeGuard.client_mode,
    session_state: routeGuard.session_state,
    session_id_present: routeGuard.session_id_present,
    owner_scope_source: routeGuard.owner_scope_source,
    protected_route_count: routeGuard.protected_routes.length,
    allowed_route_count: routeGuard.protected_routes.filter(route => route.allowed).length,
    blocked_reasons: [...routeGuard.blocked_reasons],
    metadata: routeGuard.metadata
  };
}

export function ownerScopeFromSessionState(sessionState) {
  if (
    !sessionState ||
    sessionState.status !== "authenticated" ||
    sessionState.tenantRef?.type !== "oa.tenant" ||
    sessionState.subjectRef?.type !== "oa.user"
  ) {
    return null;
  }
  return {
    tenantId: sessionState.tenantRef.id,
    ownerUserId: sessionState.subjectRef.id,
    uploadedByUserId: sessionState.subjectRef.id,
    source: "session-claims"
  };
}

function routeGuardStatus({ fetchModeRequested, fetchModeAllowed, clientMode }) {
  if (fetchModeRequested && !fetchModeAllowed) return "blocked";
  if (fetchModeAllowed) return "allowed";
  if (clientMode === "mock") return "mock_preview";
  return "blocked";
}
