import { useEffect, useRef } from "react";
import { authClient } from "@/lib/auth-client";
import { API_BASE_URL } from "@/lib/api-base";

type MessageHandler = (message: any) => void;

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

export function useRealtimeChannel(channel: string, onMessage: MessageHandler, enabled: boolean = true) {
  const onMessageRef = useRef<MessageHandler>(onMessage);
  const retriesRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      const token = authClient.getAccessToken();
      if (!token) return;

      try {
        const ws = new WebSocket(buildWsUrl(`/realtime/ws/${channel}`, token));
        socketRef.current = ws;

        ws.onopen = () => {
          retriesRef.current = 0;
        };

        ws.onmessage = (evt) => {
          try {
            const payload = JSON.parse(evt.data);
            onMessageRef.current(payload);
          } catch {
            // Ignore malformed frames
          }
        };

        ws.onclose = async () => {
          if (stopped) return;
          if (!authClient.getAccessToken()) {
            const refreshed = await authClient.refresh();
            if (!refreshed) return;
          }
          const attempt = Math.min(retriesRef.current + 1, 6);
          retriesRef.current = attempt;
          const backoff = Math.min(1000 * 2 ** attempt, 15000);
          reconnectTimer = setTimeout(() => {
            void connect();
          }, backoff);
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch {
        const attempt = Math.min(retriesRef.current + 1, 6);
        retriesRef.current = attempt;
        const backoff = Math.min(1000 * 2 ** attempt, 15000);
        reconnectTimer = setTimeout(() => {
          void connect();
        }, backoff);
      }
    };

    void connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [channel, enabled]);
}
