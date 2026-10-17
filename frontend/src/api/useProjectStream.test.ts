import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScrapEvent } from "../types/events";

/** Minimal stand-in for the browser EventSource. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  readyState = FakeEventSource.OPEN;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>();
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  /** Simulate a server-sent message. */
  emit(data: string, type?: string, lastEventId = "") {
    const event = new MessageEvent(type ?? "message", { data, lastEventId });
    if (type) this.listeners.get(type)?.forEach((fn) => fn(event));
    else this.onmessage?.(event);
  }
  /** Simulate the browser giving up on the connection (e.g. a 502 during a backend restart). */
  fail() {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.(new Event("error"));
  }
}

const replyEvent = (projectId = "p1"): ScrapEvent => ({
  id: "e1",
  type: "chat_reply",
  project_id: projectId,
  created_at: "2026-10-17T00:00:00Z",
  payload: { id: "m1", project_id: projectId, role: "assistant", content: "hi", created_at: "2026-10-17T00:00:00Z" },
});

async function loadHook(useMock: "true" | "false") {
  vi.resetModules();
  vi.stubEnv("VITE_USE_MOCK", useMock);
  const { useProjectStream } = await import("./useProjectStream");
  const mockEvents = await import("./mockEvents");
  return { useProjectStream, ...mockEvents };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useProjectStream (backend)", () => {
  it("opens the project's SSE stream and forwards named events", async () => {
    const { useProjectStream } = await loadHook("false");
    const onEvent = vi.fn();
    renderHook(() => useProjectStream("p1", onEvent));
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/api/projects/p1/events");
    source.emit(JSON.stringify(replyEvent()), "chat_reply");
    expect(onEvent).toHaveBeenCalledWith(replyEvent());
  });

  it("skips a malformed message instead of throwing, and keeps listening", async () => {
    const { useProjectStream } = await loadHook("false");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const onEvent = vi.fn();
    renderHook(() => useProjectStream("p1", onEvent));
    const source = FakeEventSource.instances[0];
    expect(() => source.emit("{not json")).not.toThrow();
    expect(warn).toHaveBeenCalled();
    source.emit(JSON.stringify(replyEvent()));
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("reconnects after the browser closes a failed stream", async () => {
    vi.useFakeTimers();
    const { useProjectStream } = await loadHook("false");
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const onEvent = vi.fn();
    renderHook(() => useProjectStream("p1", onEvent));
    FakeEventSource.instances[0].fail();
    vi.advanceTimersByTime(5000);
    expect(FakeEventSource.instances).toHaveLength(2);
    FakeEventSource.instances[1].emit(JSON.stringify(replyEvent()));
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("closes the stream when the project changes or the view unmounts", async () => {
    vi.useFakeTimers();
    const { useProjectStream } = await loadHook("false");
    const { rerender, unmount } = renderHook(({ id }) => useProjectStream(id, vi.fn()), {
      initialProps: { id: "p1" },
    });
    rerender({ id: "p2" });
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(FakeEventSource.instances[1].url).toBe("/api/projects/p2/events");
    unmount();
    expect(FakeEventSource.instances[1].closed).toBe(true);
    // No reconnect after unmount.
    FakeEventSource.instances[1].fail();
    vi.advanceTimersByTime(10000);
    expect(FakeEventSource.instances).toHaveLength(2);
  });
});

describe("useProjectStream (resume points)", () => {
  it("starts after the snapshot's last event id", async () => {
    const { useProjectStream } = await loadHook("false");
    renderHook(() => useProjectStream("p1", vi.fn(), 42));
    expect(FakeEventSource.instances[0].url).toBe("/api/projects/p1/events?after=42");
  });

  it("starts from now when no snapshot id is known", async () => {
    const { useProjectStream } = await loadHook("false");
    renderHook(() => useProjectStream("p1", vi.fn()));
    expect(FakeEventSource.instances[0].url).toBe("/api/projects/p1/events");
  });

  it("reconnects from the last event it received", async () => {
    vi.useFakeTimers();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { useProjectStream } = await loadHook("false");
    renderHook(() => useProjectStream("p1", vi.fn(), 10));
    const first = FakeEventSource.instances[0];
    first.emit(JSON.stringify(replyEvent()), "chat_reply", "17");
    first.fail();
    vi.advanceTimersByTime(5000);
    expect(FakeEventSource.instances[1].url).toBe("/api/projects/p1/events?after=17");
  });

  it("delivers backend-only events (user_message, run_status)", async () => {
    const { useProjectStream } = await loadHook("false");
    const onEvent = vi.fn();
    renderHook(() => useProjectStream("p1", onEvent));
    const source = FakeEventSource.instances[0];
    source.emit(JSON.stringify({ type: "run_status", project_id: "p1", payload: { status: "running" } }), "run_status");
    source.emit(JSON.stringify({ type: "user_message", project_id: "p1", payload: {} }), "user_message");
    expect(onEvent.mock.calls.map(([e]) => e.type)).toEqual(["run_status", "user_message"]);
  });
});

describe("useProjectStream (mock)", () => {
  it("delivers events from the mock bus and stops after unmount", async () => {
    const { useProjectStream, publishMockEvent } = await loadHook("true");
    const onEvent = vi.fn();
    const { unmount } = renderHook(() => useProjectStream("p1", onEvent));
    publishMockEvent(replyEvent());
    expect(onEvent).toHaveBeenCalledTimes(1);
    unmount();
    publishMockEvent(replyEvent());
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
