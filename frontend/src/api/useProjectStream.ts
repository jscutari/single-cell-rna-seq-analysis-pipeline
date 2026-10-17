import { useEffect, useRef } from "react";
import { EVENT_TYPES } from "../types/events";
import { BACKEND_EVENT_TYPES, type StreamEvent } from "../types/ui";
import { USE_MOCK } from "./client";
import { subscribeMockEvents } from "./mockEvents";

/** Wait before reopening a stream the browser gave up on (e.g. backend restarting). */
const RECONNECT_DELAY_MS = 3000;

/**
 * Subscribes to a project's live event stream (GET /api/projects/{id}/events, SSE).
 * In mock mode, events come from the in-memory mock bus instead.
 *
 * `after` is the last event id the app already has (from /state); the stream
 * starts right after it. Reconnects resume from the last event received.
 */
export function useProjectStream(
  projectId: string | null,
  onEvent: (event: StreamEvent) => void,
  after?: number,
) {
  // Keep the latest handler and start point without resubscribing on every render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const afterRef = useRef(after);
  afterRef.current = after;

  useEffect(() => {
    if (!projectId) return;

    if (USE_MOCK) {
      // The mock bus delivers every project's events; handlers route by event.project_id,
      // so a reply still lands if the user switched projects while waiting.
      return subscribeMockEvents((event) => handlerRef.current(event));
    }

    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let lastId: number | undefined = afterRef.current;

    const handle = (e: MessageEvent<string>) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(e.data) as StreamEvent;
      } catch {
        console.warn("[stream] skipped malformed event", e.data);
        return;
      }
      const id = Number(e.lastEventId);
      if (Number.isFinite(id) && e.lastEventId !== "") lastId = id;
      handlerRef.current(event);
    };

    const connect = () => {
      const from = lastId ?? afterRef.current;
      const query = from === undefined ? "" : `?after=${from}`;
      source = new EventSource(`/api/projects/${projectId}/events${query}`);
      // The backend sends named SSE events (event: <type>); accept unnamed ones too.
      source.onmessage = handle;
      [...EVENT_TYPES, ...BACKEND_EVENT_TYPES].forEach((type) => source!.addEventListener(type, handle));
      source.onerror = () => {
        // Transient drops reconnect on their own (readyState CONNECTING). An error
        // response closes the stream for good, so reopen it ourselves.
        if (stopped || source?.readyState !== EventSource.CLOSED) return;
        console.warn(`[stream] connection closed; retrying in ${RECONNECT_DELAY_MS / 1000}s`);
        retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      source?.close();
    };
  }, [projectId]);
}
