import { useEffect, useRef, useState } from "react";
import { authClient } from "@/lib/auth-client";
import { API_BASE_URL } from "@/lib/api-base";

type MessageHandler = (message: any) => void;

// A quiet socket is closed by proxies and some office networks after 30-100 s without traffic, and the
// screen then silently stops updating. A ping every 25 s keeps it open (the server answers "pong").
const HEARTBEAT_MS = 25_000;

function buildWsUrl(path: string, token: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (API_BASE_URL) {
    const withToken = `${API_BASE_URL}${normalized}?token=${encodeURIComponent(token)}`;
    if (withToken.startsWith("https://")) return withToken.replace("https://", "wss://");
    if (withToken.startsWith("http://")) return withToken.replace("http://", "ws://");
    return withToken;
  }
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const withToken = `${origin}${normalized}?token=${encodeURIComponent(token)}`;
  if (withToken.startsWith("https://")) return withToken.replace("https://", "wss://");
  return withToken.replace("http://", "ws://");
}

/**
 * Subscribe to a server realtime channel. Messages go to `onMessage`; "pong" heartbeats are swallowed.
 * After a dropped connection comes back, `onMessage({ event: "reconnected" })` is called once - anything
 * sent while it was down was missed, so listeners should refresh what they show.
 * Returns whether the socket is open now (a listener can fall back to polling while it is not).
 */
export function useRealtimeChannel(channel: string, onMessage: MessageHandler, enabled: boolean = true): boolean {
  const onMessageRef = useRef<MessageHandler>(onMessage);
  const retriesRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);

  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let everOpened = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;

    const stopHeartbeat = () => {
      if (heartbeat) clearInterval(heartbeat);
      heartbeat = null;
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      const attempt = Math.min(retriesRef.current + 1, 6);
      retriesRef.current = attempt;
      const backoff = Math.min(1000 * 2 ** attempt, 15000);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => { void connect(); }, backoff);
    };

    const connect = async () => {
      if (stopped) return;
      const token = authClient.getAccessToken();
      if (!token) return;

      try {
        const ws = new WebSocket(buildWsUrl(`/realtime/ws/${channel}`, token));
        socketRef.current = ws;

        ws.onopen = () => {
          retriesRef.current = 0;
          setConnected(true);
          stopHeartbeat();
          heartbeat = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              try { ws.send(JSON.stringify({ type: "ping" })); } catch { /* the close handler reconnects */ }
            }
          }, HEARTBEAT_MS);
          if (everOpened) {
            try { onMessageRef.current({ event: "reconnected", channel }); } catch { /* listener's own error */ }
          }
          everOpened = true;
        };

        ws.onmessage = (evt) => {
          try {
            const payload = JSON.parse(evt.data);
            if (payload?.event === "pong") return;
            onMessageRef.current(payload);
          } catch {
            // Ignore malformed frames
          }
        };

        ws.onclose = async (evt) => {
          stopHeartbeat();
          setConnected(false);
          if (stopped) return;
          // 4401 = auth failure (invalid/expired token) — force refresh; stop if session is gone
          if (evt.code === 4401 || !authClient.getAccessToken()) {
            const refreshed = await authClient.refresh();
            if (!refreshed) return;
          }
          scheduleReconnect();
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        scheduleReconnect();
      }
    };

    // A laptop waking from sleep or a phone coming back to the app: reconnect at once rather than
    // waiting out the back-off, and catch up.
    const onWake = () => {
      if (document.visibilityState !== "visible" || stopped) return;
      const ws = socketRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        retriesRef.current = 0;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        void connect();
      }
    };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);

    void connect();

    return () => {
      stopped = true;
      stopHeartbeat();
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("online", onWake);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
      setConnected(false);
    };
  }, [channel, enabled]);

  return connected;
}
