import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  anonymousSessionState,
  type SessionState,
} from "../domain/session";

interface SessionContextValue {
  readonly sessionState: SessionState;
  readonly setSessionState: (sessionState: SessionState) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  initialSession = anonymousSessionState,
}: {
  readonly children: ReactNode;
  readonly initialSession?: SessionState;
}) {
  const [sessionState, setSessionState] = useState(initialSession);
  const value = useMemo(
    () => ({ sessionState, setSessionState }),
    [sessionState],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}
