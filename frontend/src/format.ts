/* Display helpers shared by every page. */

export const number = (value: unknown) => Number(value || 0).toLocaleString();

export function date(value: string | null | undefined) {
  if (!value) return "Just started";
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : value + "Z");
  return Number.isNaN(d.valueOf()) ? "Date unavailable" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Only http(s) links ever reach an href; anything else (javascript:, data:, …) becomes "". */
export function safeUrl(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  try {
    const u = new URL(value);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : "";
  } catch {
    return "";
  }
}

/** Same-origin paths from the API (report links). Rejects protocol-relative and absolute URLs. */
export function safePath(value: unknown): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") ? value : "";
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((x) => x[0] ?? "")
    .join("")
    .toUpperCase();

/** A blob download without navigating away. */
export function saveFile(blob: Blob, name: string) {
  const address = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = address;
  a.download = name;
  a.rel = "noopener";
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(address), 1000);
}
