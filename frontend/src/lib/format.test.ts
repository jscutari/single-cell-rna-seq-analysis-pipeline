import { expect, it } from "vitest";
import { formatBytes, formatP } from "./format";

it("formats file sizes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(3 * 1024)).toBe("3.0 KB");
  expect(formatBytes(1.8 * 1024 ** 3)).toBe("1.8 GB");
  expect(formatBytes(20 * 1024 ** 2)).toBe("20 MB");
});

it("formats p-values", () => {
  expect(formatP(2.1e-8)).toBe("2.1e−8");
  expect(formatP(0.0123)).toBe("0.012");
  expect(formatP(1.2e-3)).toBe("1.2e−3"); // was shown as "0.001"
});
