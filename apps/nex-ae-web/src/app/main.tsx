import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createInstalledBrowserRuntime } from "./runtime/installedRuntime";
import { StartupFailure } from "./runtime/StartupFailure";
import "../design-system/tokens/tokens.css";

const rootElement = document.getElementById("modern-root");

if (!rootElement) {
  throw new Error("NeX AE modern root element was not found");
}

let application;
try {
  const runtime = createInstalledBrowserRuntime();
  application = <App runtime={runtime} />;
} catch {
  application = <StartupFailure />;
}

createRoot(rootElement).render(<StrictMode>{application}</StrictMode>);
