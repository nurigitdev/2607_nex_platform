import { BrowserRouter } from "react-router-dom";

import type { SessionState } from "./domain/session";
import type { SessionClientPort } from "./legacyAdapters/sessionAdapter";
import type { InstalledBrowserRuntime } from "./runtime/installedRuntime";
import { AppProviders } from "./providers/AppProviders";
import { AppRouter } from "./router/AppRouter";

export function App({
  initialSession,
  sessionClient,
  tenantId,
  runtime,
}: {
  readonly initialSession?: SessionState;
  readonly sessionClient?: SessionClientPort;
  readonly tenantId?: string;
  readonly runtime?: InstalledBrowserRuntime;
}) {
  return (
    <BrowserRouter>
      <AppProviders
        initialSession={initialSession}
        sessionClient={sessionClient ?? runtime?.sessionClient}
        tenantId={tenantId ?? runtime?.tenantId}
        runtime={runtime}
      >
        <AppRouter />
      </AppProviders>
    </BrowserRouter>
  );
}
