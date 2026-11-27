const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const KEY_STORAGE = "kt.apiKey";

export const DEV_IDENTITIES = [
  { key: "dev-admin-key", label: "Admin / auditor (privileged map)" },
  { key: "dev-engineering-key", label: "Eva — Engineering" },
  { key: "dev-hr-key", label: "Harry — People Ops" },
  { key: "dev-agent-key", label: "AI agent (engineering scope)" },
];

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) || "dev-admin-key";
  } catch {
    return "dev-admin-key";
  }
}

export function setApiKey(key: string) {
  try {
    localStorage.setItem(KEY_STORAGE, key);
  } catch {
    /* storage unavailable — key lives for this page only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public traceId?: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-API-Key": getApiKey(), ...(init.headers || {}) },
  });
  if (!res.ok) {
    let code = "HTTP_ERROR", message = res.statusText, trace: string | undefined;
    try {
      const body = await res.json();
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
      trace = body.error?.trace_id;
    } catch { /* not json */ }
    throw new ApiError(res.status, code, message, trace);
  }
  return res.json() as Promise<T>;
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? "?" + s : "";
};
