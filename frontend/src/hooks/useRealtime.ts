import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken, wsUrl } from "../lib/api";

/**
 * WebSocket hook — real-time inbox updates with auto-reconnect (backoff).
 * Server events invalidate TanStack Query caches, so every open panel updates
 * without refresh: message.created, conversation.updated, notification.created,
 * eitaa_account.updated.
 */
export function useRealtime(enabled: boolean) {
  const queryClient = useQueryClient();
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let closedByUs = false;

    const handleMessage = (raw: MessageEvent) => {
      try {
        const event = JSON.parse(raw.data as string) as {
          type: string;
          payload: Record<string, unknown>;
        };
        switch (event.type) {
          case "message.created":
          case "message.updated": {
            const conversationId = event.payload.conversation_id as number | undefined;
            queryClient.invalidateQueries({ queryKey: ["conversations"] });
            if (conversationId) {
              queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
              queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
            }
            break;
          }
          case "conversation.updated": {
            const conversationId = event.payload.id as number | undefined;
            queryClient.invalidateQueries({ queryKey: ["conversations"] });
            if (conversationId) {
              queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
            }
            queryClient.invalidateQueries({ queryKey: ["dashboard"] });
            break;
          }
          case "notification.created":
            queryClient.invalidateQueries({ queryKey: ["notifications"] });
            queryClient.invalidateQueries({ queryKey: ["unread-count"] });
            break;
          case "eitaa_account.updated":
            queryClient.invalidateQueries({ queryKey: ["eitaa-accounts"] });
            break;
          default:
            break;
        }
      } catch {
        /* malformed frame */
      }
    };

    const connect = () => {
      const token = getAccessToken();
      if (!token) {
        timerRef.current = setTimeout(connect, 3000);
        return;
      }
      const socket = new WebSocket(wsUrl(token));
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        // keepalive
        const ping = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, 25000);
        socket.addEventListener("close", () => clearInterval(ping), { once: true });
      };

      socket.onmessage = handleMessage;

      socket.onclose = () => {
        if (closedByUs) return;
        const delay = Math.min(15000, 1000 * 2 ** retryRef.current);
        retryRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      closedByUs = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, [enabled, queryClient]);
}
