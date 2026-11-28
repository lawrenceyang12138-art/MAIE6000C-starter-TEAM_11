import React from "react";
import { createRoot } from "react-dom/client";
import App from "./app.jsx";
import { ErrorBoundary } from "./error-boundary.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
