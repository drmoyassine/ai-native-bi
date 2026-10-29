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

export interface Organization {
  name: string;
  name_secondary: string | null;
  secondary_language: string | null;
  default_locale: string;
  accent_color: string | null;
}

export interface Me {
  user: User;
  datasets: string[];
  organization: Organization;
  language: string | null;
  locale: string;
}

export type SyncStatus = 'queued' | 'running' | 'review' | 'loaded' | 'failed' | 'stale';

export interface SourceType {
  type: string;
  label: string;
  hint: string;
  available: boolean;
  step?: string;
}

export interface SourceSummary {
  id: string;
  name: string;
  type: string;
  state: 'draft' | 'live' | 'paused';
  dataset: string | null;
  last_sync: string | null;
  waiting: number;
  last_status: SyncStatus | null;
}

export interface Sync {
  id: string;
  as_of: string;
  sheet: string | null;
  file_name: string | null;
  status: SyncStatus;
  rows: number | null;
  repeat: boolean | null;
  tests: number | null;
  note: string | null;
  error: string | null;
  found_header_row: number | null;
  created_at: string;
  by_name: string | null;
}

export interface Source {
  id: string;
  name: string;
  type: string;
  state: 'draft' | 'live' | 'paused';
  dataset: string | null;
  approved_by: string | null;
  syncs: Sync[];
}

export interface ReviewColumn {
  name: string;
  header: string;
  kind: string | null;
  summary: string | null;
}

export interface Part {
  name: string;
  label: string;
  description: string;
  required: boolean;
}

export interface AgentState {
  state: 'queued' | 'running' | 'proposed' | 'failed' | 'none';
  reason?: string;
  error?: string;
  model?: string;
  provider?: string;
  earlier?: boolean;
  header?: { row: number; reason: string | null } | null;
  dropped?: string[];
  column_notes?: Record<string, string>;
  sample?: { rows: number; masked: Record<string, string[]> } | null;
}

export interface Reason {
  column: string | null;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  by: string;
}

export interface Review {
  sync: { id: string; status: SyncStatus; file_name: string; rows: number | null; note: string | null; error: string | null };
  source: { id: string; name: string; state: string };
  dataset: string | null;
  header: { row: number | null; above_header?: string[]; guessed?: boolean; dropped_columns?: number; dropped_total_rows?: number };
  columns: ReviewColumn[];
  parts: Part[];
  mapping: Record<string, string | null> | null;
  mapping_status: 'proposed' | 'approved' | null;
  proposed_by: 'rules' | 'agent' | 'person' | null;
  reasons: Record<string, Reason> | null;
  model?: string | null;
  agent: AgentState | null;
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
