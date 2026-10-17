import { render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ChatMessage } from "../../types/schemas";
import { ChatView } from "./ChatView";

const msg = (id: string, projectId: string): ChatMessage => ({
  id,
  project_id: projectId,
  role: "user",
  content: id,
  created_at: "2026-10-17T00:00:00Z",
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

it("scrolls to the newest message when switching to a conversation of the same length", () => {
  const { rerender } = render(<ChatView messages={[msg("a1", "a"), msg("a2", "a")]} awaitingReply={false} />);
  const scroll = vi.mocked(Element.prototype.scrollIntoView);
  const before = scroll.mock.calls.length;
  rerender(<ChatView messages={[msg("b1", "b"), msg("b2", "b")]} awaitingReply={false} />);
  expect(scroll.mock.calls.length).toBeGreaterThan(before);
});
