import { describe, expect, it } from "vitest";
import { chatTitle } from "./chatTitle";

describe("chatTitle", () => {
  it.each([
    ["Can you check HLA class II in monocytes?", "Check HLA class II in monocytes"],
    ["hi! please compare neutrophils between groups.", "Compare neutrophils between groups"],
    ["Which cell types change most? Also plot them.", "Which cell types change most"],
    ["I'd like to see the interferon response", "See the interferon response"],
    ["  what   does this dataset contain  ", "What does this dataset contain"],
  ])("%s -> %s", (input, expected) => {
    expect(chatTitle(input)).toBe(expected);
  });

  it("cuts long titles at a word boundary", () => {
    const title = chatTitle("Summarize the developing neutrophil population in ventilated patients please");
    expect(title).toBe("Summarize the developing neutrophil…");
    expect(title.length).toBeLessThanOrEqual(41);
  });

  it("falls back when nothing is left", () => {
    expect(chatTitle("")).toBe("New chat");
    expect(chatTitle("hello!")).toBe("New chat");
  });
});
