// Frontend-only view types. NOT part of the shared contract (shared/), so
// check:contract ignores this file.
//
// Pending contract (ask Alex): shared/ has no Chat model and ChatMessage has no
// chat_id, so multiple chats per project live only in the UI for now. Once the
// contract has them, replace Chat with the shared model and route replies by chat_id.

export interface Chat {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
}

/** What the main page is showing. */
export type View =
  | { kind: "home" }
  | { kind: "project"; projectId: string }
  | { kind: "chat"; projectId: string; chatId: string };
