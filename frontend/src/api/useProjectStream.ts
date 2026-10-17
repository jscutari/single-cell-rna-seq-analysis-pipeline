import { useEffect, useRef } from "react";
import { EVENT_TYPES, type ScrapEvent } from "../types/events";
import { USE_MOCK } from "./client";
import { subscribeMockEvents } from "./mockEvents";

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
      return subscribeMockEvents((event) => {
        if (event.project_id === projectId) handlerRef.current(event);
      });
    }

    const source = new EventSource(`/api/projects/${projectId}/events`);
    const handle = (e: MessageEvent<string>) => handlerRef.current(JSON.parse(e.data) as ScrapEvent);
    // The backend may send named SSE events (event: <type>) or unnamed ones; accept both.
    source.onmessage = handle;
    EVENT_TYPES.forEach((type) => source.addEventListener(type, handle));
    return () => source.close();
  }, [projectId]);
}
