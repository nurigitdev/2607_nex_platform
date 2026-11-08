import { BrowserRouter } from "react-router-dom";

import type { SessionState } from "./domain/session";
import { AppProviders } from "./providers/AppProviders";
import { AppRouter } from "./router/AppRouter";

export function App({ initialSession }: { readonly initialSession?: SessionState }) {
  return (
    <BrowserRouter>
      <AppProviders initialSession={initialSession}>
        <AppRouter />
      </AppProviders>
    </BrowserRouter>
  );
}
