// Sample chats per project for mock mode; replaced by backend data later.
import type { Chat } from "../types/ui";
import type { ChatMessage } from "../types/schemas";

const HOUR = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

const SEED: Record<string, [string, string][]> = {
  p1: [
    ["Which cell types change most between COVID and healthy donors?", "Classical monocytes and plasmablasts show the largest shifts in abundance."],
    ["Is the interferon signature driven by one donor?", "No: the ISG score is elevated in 6 of 7 patients after pseudobulking by donor."],
    ["Check HLA class II expression in monocytes.", "HLA-DR genes are down in CD14 monocytes (log2FC −1.1, p_adj 3e−6)."],
    ["Summarize the developing neutrophil population.", "A small cluster expresses immature neutrophil markers (ELANE, MPO) mainly in ventilated patients."],
  ],
};
const DEFAULT_SEED: [string, string][] = [["What does this dataset contain?", "Single-cell RNA-seq counts with donor, condition and cell-type annotations."]];

/** Chat ids are stable ("<project>-chat-<n>") so tests and screenshots are predictable. */
export function mockChatsFor(projectId: string): { chats: Chat[]; messages: Record<string, ChatMessage[]> } {
  const seed = SEED[projectId] ?? (projectId.startsWith("p") ? DEFAULT_SEED : []);
  const chats: Chat[] = [];
  const messages: Record<string, ChatMessage[]> = {};
  seed.forEach(([question, answer], i) => {
    const id = `${projectId}-chat-${i + 1}`;
    const created = ago((seed.length - i) * 3 * HOUR);
    chats.push({ id, project_id: projectId, title: `Chat ${i + 1}`, created_at: created });
    messages[id] = [
      { id: `${id}-q`, project_id: projectId, role: "user", content: question, created_at: created },
      { id: `${id}-a`, project_id: projectId, role: "assistant", content: answer, created_at: created },
    ];
  });
  return { chats, messages };
}
