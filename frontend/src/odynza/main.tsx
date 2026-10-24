import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// The Watch components keep their own class names, so the shared stylesheets come first and odynza.css restyles them.
import "../styles";
import "./odynza-dark.css";
import "./odynza-light.css";
import "./odynza.css";
import "./plan2/plan2.css";
import { OdynzaApp } from "./OdynzaApp";
import { applyTheme, savedTheme } from "./Theme";

applyTheme(savedTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <OdynzaApp />
  </StrictMode>,
);
