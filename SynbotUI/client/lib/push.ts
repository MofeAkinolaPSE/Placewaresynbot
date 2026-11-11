/**
 * Phone / desktop notifications (Web Push) for this device - client, 6 Nov: "the finance team and the CFO have
 * the app on their phones; tell them when an invoice is waiting for their approval".
 *
 * Works on HTTPS with a trusted certificate. Android Chrome and desktop browsers: straight from the site.
 * iPhone: iOS 16.4 or later, and only once ACE has been added to the Home Screen (Share > Add to Home Screen)
 * and opened from there.
 */
import { api } from "@/lib/api-client";

export type PushState = "unsupported" | "needs-install" | "blocked" | "off" | "on";

const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || (navigator as any).standalone === true;

export function pushSupported(): boolean {
  return typeof window !== "undefined" && window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

let registration: Promise<ServiceWorkerRegistration | null> | null = null;

/** Register the service worker once (also makes ACE installable). Safe to call anywhere. */
export function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (registration) return registration;
  if (typeof window === "undefined" || !("serviceWorker" in navigator) || !window.isSecureContext) {
    registration = Promise.resolve(null);
    return registration;
  }
  registration = navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => null);
  // a tapped notification asks an open window to go to its page
  navigator.serviceWorker.addEventListener("message", (e: MessageEvent) => {
    if (e.data?.type === "ace:navigate" && typeof e.data.url === "string") window.location.hash = e.data.url.replace(/^#/, "");
  });
  return registration;
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return isIos() && !isStandalone() ? "needs-install" : "unsupported";
  if (Notification.permission === "denied") return "blocked";
  const reg = await registerServiceWorker();
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  return sub && Notification.permission === "granted" ? "on" : "off";
}

function keyBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** Ask the browser's permission (must run from a tap/click) and register this device. */
export async function turnPushOn(): Promise<PushState> {
  if (!pushSupported()) return pushState();
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "blocked" : "off";
  const reg = await registerServiceWorker();
  if (!reg) return "unsupported";
  const { public_key } = await api.push.publicKey();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) });
  await api.push.subscribe(sub.toJSON());
  return "on";
}

export async function turnPushOff(): Promise<PushState> {
  const reg = await registerServiceWorker();
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  if (sub) {
    try { await api.push.unsubscribe(sub.endpoint); } catch { /* removed server-side next time it fails */ }
    await sub.unsubscribe();
  }
  return pushState();
}

/** After signing in: a device that already has notifications on is (re)linked to this login. */
export async function relinkPush(): Promise<void> {
  try {
    if (!pushSupported() || Notification.permission !== "granted") return;
    const reg = await registerServiceWorker();
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) await api.push.subscribe(sub.toJSON());
  } catch { /* best effort */ }
}
