import { createContext, useContext } from "react";
import type { ReactNode } from "react";

import type { InstalledBrowserRuntime } from "../runtime/installedRuntime";

const RuntimeContext = createContext<InstalledBrowserRuntime | null>(null);

export function RuntimeProvider({
  children,
  runtime,
}: {
  readonly children: ReactNode;
  readonly runtime?: InstalledBrowserRuntime;
}) {
  return <RuntimeContext.Provider value={runtime ?? null}>{children}</RuntimeContext.Provider>;
}

export function useInstalledRuntime() {
  const runtime = useContext(RuntimeContext);
  if (!runtime) throw new Error("Installed runtime is unavailable");
  return runtime;
}

export function useOptionalInstalledRuntime() {
  return useContext(RuntimeContext);
}
