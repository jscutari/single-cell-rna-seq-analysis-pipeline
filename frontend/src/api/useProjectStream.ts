import { useEffect, useRef } from "react";
import { EVENT_TYPES, type ScrapEvent } from "../types/events";
import { USE_MOCK } from "./client";
import { subscribeMockEvents } from "./mockEvents";

/** Wait before reopening a stream the browser gave up on (e.g. backend restarting). */
const RECONNECT_DELAY_MS = 3000;

/**
 * Subscribes to a project's live event stream (GET /api/projects/{id}/events, SSE).
 * In mock mode, events come from the in-memory mock bus instead.
 */
export function useProjectStream(projectId: string | null, onEvent: (event: ScrapEvent) => void) {
  // Keep the latest handler without resubscribing on every render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

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

    const handle = (e: MessageEvent<string>) => {
      let event: ScrapEvent;
      try {
        event = JSON.parse(e.data) as ScrapEvent;
      } catch {
        console.warn("[stream] skipped malformed event", e.data);
        return;
      }
      handlerRef.current(event);
    };

    const connect = () => {
      source = new EventSource(`/api/projects/${projectId}/events`);
      // The backend may send named SSE events (event: <type>) or unnamed ones; accept both.
      source.onmessage = handle;
      EVENT_TYPES.forEach((type) => source!.addEventListener(type, handle));
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
