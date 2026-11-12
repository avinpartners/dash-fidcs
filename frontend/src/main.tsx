import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { App } from "./App";
import { applyTheme, storedTheme } from "./lib/theme";
// Montserrat (AVIN's typeface, SIL OFL), served by the app itself: latin subset, the weights the styles use.
// Guia de Identidade Visual AVIN: Rubik nos títulos, Montserrat no texto (SIL OFL, servidas pelo próprio app).
import "@fontsource/rubik/latin-500.css";
import "@fontsource/rubik/latin-600.css";
import "@fontsource/montserrat/latin-400.css";
import "@fontsource/montserrat/latin-500.css";
import "@fontsource/montserrat/latin-600.css";
import "@fontsource/montserrat/latin-700.css";
import "./styles.css";

applyTheme(storedTheme());

// Online version (GitHub Pages): no server to answer deep links, so the route lives after "#".
const Router = import.meta.env.VITE_STATIC === "1" ? HashRouter : BrowserRouter;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <App />
    </Router>
  </React.StrictMode>,
);
