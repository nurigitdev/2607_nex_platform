export interface SessionRef {
  readonly type: string;
  readonly id: string;
}

export interface SessionState {
  readonly status: "anonymous" | "authenticated" | "expired";
  readonly sessionId?: string | null;
  readonly tenantRef?: SessionRef | null;
  readonly subjectRef?: SessionRef | null;
  readonly scopes: readonly string[];
  readonly roles: readonly string[];
  readonly reason?: string | null;
}

export const anonymousSessionState: SessionState = Object.freeze({
  status: "anonymous",
  sessionId: null,
  tenantRef: null,
  subjectRef: null,
  scopes: Object.freeze([]),
  roles: Object.freeze([]),
  reason: "not_authenticated",
});
