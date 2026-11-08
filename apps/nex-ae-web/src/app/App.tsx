import { BrowserRouter } from "react-router-dom";

import type { SessionState } from "./domain/session";
import type { SessionClientPort } from "./legacyAdapters/sessionAdapter";
import { AppProviders } from "./providers/AppProviders";
import { AppRouter } from "./router/AppRouter";

export function App({
  initialSession,
  sessionClient,
  tenantId,
}: {
  readonly initialSession?: SessionState;
  readonly sessionClient?: SessionClientPort;
  readonly tenantId?: string;
}) {
  return (
    <BrowserRouter>
      <AppProviders initialSession={initialSession} sessionClient={sessionClient} tenantId={tenantId}>
        <AppRouter />
      </AppProviders>
    </BrowserRouter>
  );
}
