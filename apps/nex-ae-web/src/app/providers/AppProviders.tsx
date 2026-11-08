import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import type { SessionState } from "../domain/session";
import { I18nProvider } from "./I18nProvider";
import { SessionProvider } from "./SessionProvider";
import { ThemeProvider } from "./ThemeProvider";

export function AppProviders({
  children,
  initialSession,
}: {
  readonly children: ReactNode;
  readonly initialSession?: SessionState;
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
          <SessionProvider initialSession={initialSession}>{children}</SessionProvider>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
