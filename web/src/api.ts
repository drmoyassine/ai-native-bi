// The app's API (/app/api, src/bi/app.py). Every request that changes something carries X-BI-App: 1 (the server refuses it
// otherwise); the session is an HttpOnly cookie the browser sends by itself.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch(`/app/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: { ...(method === 'GET' ? {} : { 'X-BI-App': '1' }), ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}) },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : `error ${res.status}`);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => call<T>('GET', path),
  post: <T>(path: string, body?: unknown) => call<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => call<T>('PUT', path, body),
  delete: <T>(path: string) => call<T>('DELETE', path),
};

export interface User {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
}

export interface Upload {
  id: string;
  dataset: string;
  as_of: string;
  sheet: string | null;
  file_name: string;
  status: 'queued' | 'running' | 'loaded' | 'failed';
  rows: number | null;
  repeat: boolean | null;
  tests: number | null;
  error: string | null;
  note: string | null;
  created_at: string;
  finished_at: string | null;
  name: string;
}

export interface ModelChoice {
  model_id: string;
  name: string;
  context_window: number | null;
  price_in: number | null;
  price_out: number | null;
  default: boolean;
}

export interface ModelGroup {
  provider_id: string;
  kind: string;
  provider: string;
  data_path: string;
  models: ModelChoice[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  mode: 'ask' | 'build';
  model_id: string;
  provider: string;
  created_at: string;
}

export interface Usage {
  person: { used: number; cap: number };
  institution: { used: number; cap: number };
  month_start: string;
}

export interface ColumnMapping {
  dataset: string;
  parts: { name: string; required: boolean }[];
  columns: string[];
  mapping: Record<string, string | null>;
  status: 'proposed' | 'approved' | null;
  error: string | null;
}
