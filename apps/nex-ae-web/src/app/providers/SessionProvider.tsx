import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  anonymousSessionState,
  type SessionState,
} from "../domain/session";
import {
  buildModernCredentialLoginRequest,
  createModernSessionClient,
  type SessionClientPort,
} from "../legacyAdapters/sessionAdapter";

export type SessionPhase = "loading" | "ready" | "submitting" | "failed";

interface SessionContextValue {
  readonly sessionState: SessionState;
  readonly phase: SessionPhase;
  readonly errorStatus: string | null;
  readonly employeeId: string;
  readonly login: (input: { readonly employeeId: string; readonly password: string }) => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly expireSession: (reason?: string) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  initialSession,
  sessionClient,
  tenantId = "tenant-local",
}: {
  readonly children: ReactNode;
  readonly initialSession?: SessionState;
  readonly sessionClient?: SessionClientPort;
  readonly tenantId?: string;
}) {
  const [resolvedSessionClient] = useState(
    () => sessionClient ?? createModernSessionClient(),
  );
  const [sessionState, setSessionState] = useState(initialSession ?? anonymousSessionState);
  const [phase, setPhase] = useState<SessionPhase>(initialSession ? "ready" : "loading");
  const [errorStatus, setErrorStatus] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState("");

  useEffect(() => {
    if (initialSession) return;
    let active = true;
    resolvedSessionClient.getCurrentSession().then(
      session => {
        if (!active) return;
        setSessionState(session);
        setPhase("ready");
      },
      error => {
        if (!active) return;
        setSessionState({ ...anonymousSessionState, reason: "session_bootstrap_failed" });
        setErrorStatus(errorStatusOf(error));
        setPhase("failed");
      },
    );
    return () => { active = false; };
  }, [initialSession, resolvedSessionClient]);

  const value = useMemo<SessionContextValue>(() => ({
    sessionState,
    phase,
    errorStatus,
    employeeId,
    async login(input) {
      setPhase("submitting");
      setErrorStatus(null);
      try {
        const session = await resolvedSessionClient.login(
          buildModernCredentialLoginRequest({ tenantId, ...input }),
        );
        setSessionState(session);
        setEmployeeId(input.employeeId.trim());
        setPhase("ready");
      } catch (error) {
        setSessionState({ ...anonymousSessionState, reason: "login_failed" });
        setEmployeeId("");
        setErrorStatus(errorStatusOf(error));
        setPhase("failed");
      }
    },
    async logout() {
      setSessionState({ ...anonymousSessionState, reason: "logout" });
      setEmployeeId("");
      setErrorStatus(null);
      setPhase("ready");
      try {
        await resolvedSessionClient.logout();
      } catch {
        // Local session is cleared first; remote logout failure cannot restore access.
      }
    },
    expireSession(reason = "expired") {
      setSessionState({
        ...anonymousSessionState,
        status: "expired",
        reason,
      });
      setEmployeeId("");
      setErrorStatus(null);
      setPhase("ready");
    },
  }), [employeeId, errorStatus, phase, resolvedSessionClient, sessionState, tenantId]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}

function errorStatusOf(error: unknown) {
  if (error && typeof error === "object" && "status" in error) {
    return String(error.status);
  }
  return "SESSION_REQUEST_FAILED";
}
