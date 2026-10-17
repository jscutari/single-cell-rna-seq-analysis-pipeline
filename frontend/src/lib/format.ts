export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** p-values like "2.1e−8"; small values keep two significant digits. */
export function formatP(p: number): string {
  return p < 0.01 ? p.toExponential(1).replace("e-", "e−") : p.toFixed(3);
}
