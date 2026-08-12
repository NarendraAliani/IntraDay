// frontend/src/main.tsx
//
// React entry point. Checkpoint 4 mounted a BootstrapPlaceholder only, to
// verify the dev server/build pipeline end-to-end with no real screens.
// Checkpoint 9 replaces it with the real application root now that the
// first screen (Configuration Viewer) exists.
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import "./app/styles.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
