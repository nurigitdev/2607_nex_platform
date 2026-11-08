import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import type { SessionState } from "../domain/session";
import type { SessionClientPort } from "../legacyAdapters/sessionAdapter";
import { I18nProvider } from "./I18nProvider";
import { SessionProvider } from "./SessionProvider";
import { ThemeProvider } from "./ThemeProvider";

export function AppProviders({
  children,
  initialSession,
  sessionClient,
  tenantId,
}: {
  readonly children: ReactNode;
  readonly initialSession?: SessionState;
  readonly sessionClient?: SessionClientPort;
  readonly tenantId?: string;
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
          <SessionProvider
            initialSession={initialSession}
            sessionClient={sessionClient}
            tenantId={tenantId}
          >
            {children}
          </SessionProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
