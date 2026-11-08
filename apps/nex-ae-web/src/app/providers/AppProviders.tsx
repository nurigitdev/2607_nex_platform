import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import type { SessionState } from "../domain/session";
import type { SessionClientPort } from "../legacyAdapters/sessionAdapter";
import type { InstalledBrowserRuntime } from "../runtime/installedRuntime";
import { I18nProvider } from "./I18nProvider";
import { SessionProvider } from "./SessionProvider";
import { ThemeProvider } from "./ThemeProvider";
import { RuntimeProvider } from "./RuntimeProvider";

export function AppProviders({
  children,
  initialSession,
  sessionClient,
  tenantId,
  runtime,
}: {
  readonly children: ReactNode;
  readonly initialSession?: SessionState;
  readonly sessionClient?: SessionClientPort;
  readonly tenantId?: string;
  readonly runtime?: InstalledBrowserRuntime;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 30_000 },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ThemeProvider>
          <RuntimeProvider runtime={runtime}>
            <SessionProvider
              initialSession={initialSession}
              sessionClient={sessionClient}
              tenantId={tenantId}
            >
              {children}
            </SessionProvider>
          </RuntimeProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
