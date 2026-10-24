/* All server calls go through here: same-origin only, cookies for the session, CSRF header on writes. */
import type { DiscoveryEvent, DiscoveryResult } from "./types";

let csrfToken = "";
const WATCH_CLIENT = "radar-client";
let watchClient = (() => {
  try {
    return window.localStorage.getItem(WATCH_CLIENT) || "";
  } catch {
    return "";
  }
})();

export const watchClientId = () => watchClient;

/** The Watch client being worked on; sent with every /watch call so the server serves that client. */
export function setWatchClient(id: number | null) {
  watchClient = id ? String(id) : "";
  try {
    if (watchClient) window.localStorage.setItem(WATCH_CLIENT, watchClient);
    else window.localStorage.removeItem(WATCH_CLIENT);
  } catch {
    /* private window */
  }
}
let onSignedOut: () => void = () => {};

export function setCsrf(token: string | undefined) {
  csrfToken = token || "";
}

export function onUnauthorized(handler: () => void) {
  onSignedOut = handler;
}

function csrf(): string {
  if (csrfToken) return csrfToken;
  const match = document.cookie.match(/(?:^|;\s*)radar_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function errorMessage(r: Response, fallback: string) {
  let detail: unknown;
  try {
    detail = (await r.json()).detail;
  } catch {
    /* not JSON */
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((x: { msg?: string }) => x?.msg ?? "").filter(Boolean).join("; ");
  if (detail && typeof detail === "object" && Array.isArray((detail as { errors?: unknown }).errors))
    return ((detail as { errors: string[] }).errors).join("; ");
  return fallback;
}

export async function send(path: string, options: RequestInit = {}): Promise<Response> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD"].includes(method)) headers.set("X-CSRF-Token", csrf());
  if (watchClient && /^\/(watch|strategy|content)\b/.test(path)) headers.set("X-Watch-Client", watchClient);
  const r = await fetch(path, { ...options, method, headers, credentials: "same-origin", redirect: "error" });
  if (r.status === 401 && !path.startsWith("/auth/")) onSignedOut();
  return r;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const r = await send(path, options);
  if (!r.ok) throw new ApiError(await errorMessage(r, `Request failed (${r.status}). Check that the app is running.`), r.status);
  return (await r.json()) as T;
}

export const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

/** File downloads (PDF, images): returns the blob and the server's file name. */
export async function download(path: string, fallback: string): Promise<{ blob: Blob; name: string }> {
  const r = await send(path);
  if (!r.ok) throw new ApiError(await errorMessage(r, fallback), r.status);
  const name = (r.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || "";
  return { blob: await r.blob(), name };
}

/** Progress arrives as JSON lines: stage messages, verified companies so far, then the full result. */
export async function streamDiscovery(body: unknown, onEvent: (e: DiscoveryEvent) => void): Promise<DiscoveryResult> {
  const r = await send("/discover/stream", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok || !r.body) throw new ApiError(await errorMessage(r, `Search failed (${r.status}). Check that the app is running.`), r.status);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: DiscoveryResult | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let i: number;
    while ((i = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, i).trim();
      buffer = buffer.slice(i + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (event.type === "error") throw new ApiError(String(event.detail), 502);
      if (event.type === "result") result = event.data;
      else onEvent(event);
    }
  }
  if (!result) throw new ApiError("The search stopped before it finished. Try again.", 0);
  return result;
}
