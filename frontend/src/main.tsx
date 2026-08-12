// frontend/src/main.tsx
//
// React entry point (Checkpoint 4 §28 — minimal bootstrap only, no
// screens/business logic). Mounts a single placeholder component so the
// dev server and build pipeline can be verified end-to-end. Replace with
// real routing/screens starting at Checkpoint 14 (Frontend).
import React from "react";
import ReactDOM from "react-dom/client";

import { BootstrapPlaceholder } from "./BootstrapPlaceholder";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BootstrapPlaceholder />
  </React.StrictMode>,
);
