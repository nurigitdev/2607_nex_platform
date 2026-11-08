import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "../design-system/tokens/tokens.css";

const rootElement = document.getElementById("modern-root");

if (!rootElement) {
  throw new Error("NeX AE modern root element was not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
