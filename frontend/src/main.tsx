// frontend/src/main.tsx
//
// React entry point. Checkpoint 4 mounted a BootstrapPlaceholder only, to
// verify the dev server/build pipeline end-to-end with no real screens.
// Checkpoint 9 replaced it with the real application root once the first
// screen (Configuration Viewer) existed. Checkpoint 11 wraps it in
// `AuthProvider` - the authentication boundary must be above everything
// that might need to know "am I logged in, as whom."
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { AuthProvider } from "./common/auth/AuthContext";
import "./app/styles.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>,
);
