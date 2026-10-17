// Mirrors shared/events.py, which is the source of truth (owned with Alexandre).
import type { Brief, ChatMessage, CodeCell, Finding, Hypothesis, LLMCall } from "./schemas";

/** Same order as the EventType enum in shared/events.py. */
export const EVENT_TYPES = [
  "llm_call",
  "brief_updated",
  "hypothesis_status",
  "cell_started",
  "cell_finished",
  "finding",
  "chat_reply",
  "stage_done",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface EventPayloads {
  llm_call: LLMCall;
  brief_updated: Brief;
  hypothesis_status: Hypothesis;
  cell_started: CodeCell;
  cell_finished: CodeCell;
  finding: Finding;
  chat_reply: ChatMessage;
  stage_done: { stage: string; summary: string };
}

/** The Event envelope, narrowed by `type` so `payload` has the right shape. */
export type ScrapEvent = {
  [T in EventType]: {
    id: string;
    type: T;
    project_id: string;
    payload: EventPayloads[T];
    created_at: string;
  };
}[EventType];
