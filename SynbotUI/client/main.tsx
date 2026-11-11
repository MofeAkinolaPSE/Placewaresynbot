import { createRoot } from "react-dom/client";
import App from "./App";
import { registerServiceWorker } from "./lib/push";
import { installBranchFetch } from "./lib/branch";

// every signed-in API call carries the branch (Lagos / Abuja) this tab works in - before anything fetches
installBranchFetch();

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

// phone / desktop notifications and "Add to Home Screen" (only on the secure https address)
if (import.meta.env.PROD) window.addEventListener("load", () => { void registerServiceWorker(); });
