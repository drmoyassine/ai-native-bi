import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api } from './api';

interface Provider {
  id: string;
  kind: string;
  name: string;
  base_url: string | null;
  has_key: boolean;
  enabled: boolean;
  fetched_at: string | null;
  fetch_error: string | null;
  models: number;
  allowed: number;
  data_path: string;
  may_see_samples: boolean;
}

const SAMPLES_WARNING =
  'Masked sample rows (at most 20 per table, personal columns replaced with made-up values) will be sent to this provider when an admin sets up a source. Use this only with a provider the organization has an agreement with, or a local one. Allow it?';

interface ProviderModel {
  model_id: string;
  name: string | null;
  context_window: number | null;
  price_in: number | null;
  price_out: number | null;
  tool_support: 'yes' | 'no' | 'unknown';
  tool_support_via: string | null;
  available: boolean;
  allowed_ask: boolean;
  allowed_build: boolean;
  default_ask: boolean;
  default_build: boolean;
}

const KIND_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  openai_compatible: 'OpenAI-compatible',
  openrouter: 'OpenRouter',
  ollama: 'Ollama',
};

// Which kinds need an address and which need a key (the server checks the same; this only decides what the form asks for).
const NEEDS_ADDRESS = ['openai_compatible', 'ollama'];
const NEEDS_KEY = ['anthropic', 'openai', 'openrouter'];

/** Admin: the providers the institution uses, their keys (kept in the secret store, never shown again), the models each lists,
 * and which of them people may use. A model is allowed only if it calls tools, which the agent needs. */
export function Providers() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [secretsConfigured, setSecretsConfigured] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const r = await api.get<{ providers: Provider[]; kinds: string[]; secrets_configured: boolean }>('/admin/providers');
    setProviders(r.providers);
    setKinds(r.kinds);
    setSecretsConfigured(r.secrets_configured);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section>
      <h2>Model providers</h2>
      {!secretsConfigured && (
        <p className="error" role="alert">
          The secret store is not configured, so keys cannot be saved. Set BI_SECRETS_KEY (python3 scripts/make_env.py) and restart.
        </p>
      )}
      {notice && <p className="note" role="status">{notice}</p>}
      <AddProvider kinds={kinds} onAdded={async (error) => { setNotice(error ? `Added, but its models could not be listed: ${error}` : null); await refresh(); }} />
      {providers.length === 0 && <p className="hint">No provider yet. Add one to let people ask questions.</p>}
      {providers.map((p) => (
        <div className="card provider" key={p.id}>
          <div className="provider-head">
            <strong dir="auto">{p.name}</strong>
            <span className="note">
              {KIND_LABELS[p.kind] ?? p.kind} · {p.models} models, {p.allowed} allowed
              {p.fetched_at ? ` · listed ${new Date(p.fetched_at).toLocaleString()}` : ''}
            </span>
            <button className="link" onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}>
              {open === p.id ? 'Hide models' : 'Models'}
            </button>
          </div>
          <p className="note">{p.data_path}</p>
          <label className="inline samples">
            <input
              type="checkbox"
              checked={p.may_see_samples}
              onChange={(e) => {
                if (e.target.checked && !window.confirm(SAMPLES_WARNING)) return;
                void api.put(`/admin/providers/${p.id}`, { may_see_samples: e.target.checked }).then(refresh);
              }}
            />
            <span>
              May see sample rows during setup
              <span className="hint"> (up to 20 rows per table, names, emails and IDs replaced; off by default)</span>
            </span>
          </label>
          {p.fetch_error && <p className="error">Could not list models: {p.fetch_error}</p>}
          {open === p.id && <ModelList provider={p} onChange={refresh} onNotice={setNotice} />}
        </div>
      ))}
    </section>
  );
}

function AddProvider({ kinds, onAdded }: { kinds: string[]; onAdded: (fetchError: string | null) => Promise<void> }) {
  const [kind, setKind] = useState('anthropic');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      const body = {
        kind,
        name: String(data.get('name')),
        ...(data.get('base_url') ? { base_url: String(data.get('base_url')) } : {}),
        ...(data.get('api_key') ? { api_key: String(data.get('api_key')) } : {}),
      };
      const r = await api.post<{ fetch_error: string | null }>('/admin/providers', body);
      form.reset();
      await onAdded(r.fetch_error);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card controls" onSubmit={submit}>
      <label>
        Kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k] ?? k}
            </option>
          ))}
        </select>
      </label>
      <label>
        Name
        <input name="name" required maxLength={80} defaultValue="" />
      </label>
      {NEEDS_ADDRESS.includes(kind) && (
        <label>
          Address
          <input name="base_url" required placeholder={kind === 'ollama' ? 'http://ollama:11434' : 'https://host/v1'} />
        </label>
      )}
      <label>
        API key{NEEDS_KEY.includes(kind) ? '' : ' (if it needs one)'}
        <input name="api_key" type="password" autoComplete="off" required={NEEDS_KEY.includes(kind)} />
      </label>
      <button type="submit" disabled={busy}>
        Add provider
      </button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}

function ModelList({ provider, onChange, onNotice }: { provider: Provider; onChange: () => Promise<void>; onNotice: (s: string | null) => void }) {
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setModels((await api.get<{ models: ProviderModel[] }>(`/admin/providers/${provider.id}/models`)).models);
  }, [provider.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshModels() {
    setBusy('*');
    try {
      const r = await api.post<{ fetch_error: string | null }>(`/admin/providers/${provider.id}/refresh`);
      onNotice(r.fetch_error ? `Could not list models: ${r.fetch_error}` : null);
      await load();
      await onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function set(m: ProviderModel, patch: Partial<Pick<ProviderModel, 'allowed_ask' | 'allowed_build' | 'default_ask' | 'default_build'>>) {
    setBusy(m.model_id);
    setError(null);
    const next = { ...m, ...patch };
    if (!next.allowed_ask) next.default_ask = false;
    if (!next.allowed_build) next.default_build = false;
    try {
      await api.put('/admin/models', {
        provider_id: provider.id,
        model_id: m.model_id,
        allowed_ask: next.allowed_ask,
        allowed_build: next.allowed_build,
        default_ask: next.default_ask,
        default_build: next.default_build,
      });
      await load();
      await onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const price = (m: ProviderModel) => (m.price_in != null && m.price_out != null ? `$${m.price_in} / $${m.price_out}` : '');

  return (
    <>
      <p>
        <button onClick={() => void refreshModels()} disabled={busy === '*'}>
          Refresh the list
        </button>
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Context</th>
            <th>Tools</th>
            <th>$ per M tokens (in / out)</th>
            <th>Ask</th>
            <th>Default for ask</th>
            <th>Build</th>
            <th>Default for build</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model_id} className={m.available ? '' : 'gone'}>
              <td>
                <span dir="auto">{m.name ?? m.model_id}</span>
                {!m.available && <span className="note"> (no longer listed)</span>}
              </td>
              <td className="num">{m.context_window ? m.context_window.toLocaleString() : ''}</td>
              <td title={m.tool_support_via ? `known from ${m.tool_support_via}` : 'tested the first time it is allowed'}>{m.tool_support}</td>
              <td className="num">{price(m)}</td>
              <td>
                <input type="checkbox" aria-label={`Allow ${m.model_id} for asking`} checked={m.allowed_ask} disabled={busy === m.model_id || !m.available} onChange={(e) => void set(m, { allowed_ask: e.target.checked })} />
              </td>
              <td>
                <input type="radio" name={`default-ask-${provider.id}`} aria-label={`${m.model_id} is the default for asking`} checked={m.default_ask} disabled={!m.allowed_ask || busy === m.model_id} onChange={() => void set(m, { default_ask: true })} />
              </td>
              <td>
                <input type="checkbox" aria-label={`Allow ${m.model_id} for building`} checked={m.allowed_build} disabled={busy === m.model_id || !m.available} onChange={(e) => void set(m, { allowed_build: e.target.checked })} />
              </td>
              <td>
                <input type="radio" name={`default-build-${provider.id}`} aria-label={`${m.model_id} is the default for building`} checked={m.default_build} disabled={!m.allowed_build || busy === m.model_id} onChange={() => void set(m, { default_build: true })} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
