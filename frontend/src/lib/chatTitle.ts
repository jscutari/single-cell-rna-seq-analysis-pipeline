/**
 * A short chat title from the first message, e.g.
 * "Can you check HLA class II in monocytes?" -> "Check HLA class II in monocytes".
 * Runs in the browser so new chats get a name instantly.
 */
const LEADING_FILLER = [
  /^(hey|hi|hello)\b[,!.\s]*/i,
  /^(can|could|would|will) you\s+(please\s+)?/i,
  /^please\s+/i,
  /^i('d| would) like (you )?to\s+/i,
  /^i want (you )?to\s+/i,
  /^let'?s\s+/i,
];

export function chatTitle(text: string, maxLength = 40): string {
  let title = text.replace(/\s+/g, " ").trim().replace(LEADING_FILLER[0], "");
  title = title.split(/(?<=[.?!])\s/)[0] ?? title; // first sentence
  for (const pattern of LEADING_FILLER) title = title.replace(pattern, "");
  title = title.replace(/[\s.?!,:;]+$/, "");
  if (!title) return "New chat";
  title = title[0].toUpperCase() + title.slice(1);
  if (title.length > maxLength) {
    const cut = title.slice(0, maxLength);
    const space = cut.lastIndexOf(" ");
    title = (space > maxLength / 2 ? cut.slice(0, space) : cut).replace(/[\s,:;]+$/, "") + "…";
  }
  return title;
}
