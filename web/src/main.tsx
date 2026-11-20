import { StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/router";
import "./index.css";
import "./lib/i18n";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Translations load on demand; pages wait for theirs here or in their own boundary. */}
    <Suspense fallback={null}>
      <App />
    </Suspense>
  </StrictMode>,
);
