// Stands in for the backend's live event stream while USE_MOCK is on.
import type { ScrapEvent } from "../types/events";

type Listener = (event: ScrapEvent) => void;

const listeners = new Set<Listener>();

export function publishMockEvent(event: ScrapEvent): void {
  listeners.forEach((listener) => listener(event));
}

export function subscribeMockEvents(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
