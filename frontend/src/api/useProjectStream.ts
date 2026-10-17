import { useEffect } from "react";
import type { EventType, ScrapEvent } from "../types/events";

const EVENT_TYPES: EventType[] = [
  "llm_call",
  "brief_updated",
  "hypothesis_status",
  "cell_started",
  "cell_finished",
  "finding",
  "chat_reply",
  "stage_done",
];

const STREAM_ENABLED = false;

/**
 * Subscribes to a project's live event stream (GET /api/projects/{id}/events, SSE).
 * Disabled until the backend exists; views will pass a handler that folds events into state.
 */
export function useProjectStream(projectId: string | null, onEvent: (event: ScrapEvent) => void) {
  useEffect(() => {
    if (!STREAM_ENABLED || !projectId) return;
    const source = new EventSource(`/api/projects/${projectId}/events`);
    const handle = (e: MessageEvent<string>) => onEvent(JSON.parse(e.data) as ScrapEvent);
    // The backend may send named SSE events (event: <type>) or unnamed ones; accept both.
    source.onmessage = handle;
    EVENT_TYPES.forEach((type) => source.addEventListener(type, handle));
    return () => source.close();
  }, [projectId, onEvent]);
}
