// Mirrors shared/events.py (PLAN.md §6).
import type { Brief, ChatMessage, CodeCell, Finding, Hypothesis, LLMCall } from "./schemas";

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

export type EventType = keyof EventPayloads;

export type ScrapEvent = {
  [T in EventType]: { id?: number; type: T; project_id: string; payload: EventPayloads[T]; ts: string };
}[EventType];
