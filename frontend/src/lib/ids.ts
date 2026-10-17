/**
 * Hex id in the same format as shared.schemas.new_id() (uuid4().hex).
 * crypto.randomUUID only exists in secure contexts (https or localhost), so the app
 * would crash when opened over plain HTTP, e.g. http://<brev-ip>:5173. getRandomValues
 * works everywhere.
 */
export function newId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID().replaceAll("-", "");
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
