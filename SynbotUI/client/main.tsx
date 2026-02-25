import { createRoot } from "react-dom/client";
import App from "./App";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element not found in HTML");
}

const startRoute = (root as HTMLElement).dataset.synbotStartRoute;
if (startRoute && !window.location.hash) {
  const sanitized = startRoute.startsWith("/") ? startRoute : `/${startRoute}`;
  window.location.hash = `#${sanitized}`;
}

createRoot(root).render(<App />);
