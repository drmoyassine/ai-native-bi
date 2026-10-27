import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type User } from './api';

interface Token {
  id: string;
  name: string;
  hint: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  owner?: string;
}

interface TokenList {
  tokens: Token[];
  mcp_url: string | null;
  expiry_days: number[];
}

const date = (s: string | null) => (s ? new Date(s).toLocaleDateString() : '—');

function status(t: Token): string {
  if (t.revoked_at) return 'revoked';
  if (new Date(t.expires_at) < new Date()) return 'expired';
  return 'active';
}

/** Personal access tokens for the MCP server (docs/mcp-spec.md): an agent outside the BI (Claude Code, Claude, another assistant)
 * uses the governed metrics as you, with your rights. A token is shown once, when it is made. */
export function Tokens({ user }: { user: User }) {
  const [list, setList] = useState<TokenList | null>(null);
  const [everyone, setEveryone] = useState(false);
  const [made, setMade] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setList(await api.get<TokenList>(`/tokens${everyone ? '?everyone=true' : ''}`));
  }, [everyone]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setError(null);
    try {
      const r = await api.post<{ token: string }>('/tokens', { name: String(data.get('name')), days: Number(data.get('days')) });
      setMade(r.token);
      form.reset();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function revoke(t: Token) {
    if (!window.confirm(`Revoke "${t.name}"? Anything using it stops working at once.`)) return;
    try {
      await api.delete(`/tokens/${t.id}`);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const url = list?.mcp_url ?? '<this app>/mcp';
  const config = JSON.stringify({ mcpServers: { bi: { type: 'http', url, headers: { Authorization: 'Bearer ${BI_TOKEN}' } } } }, null, 2);

  return (
    <section>
      <h2>Access tokens</h2>
      <p className="note">
        A token lets an agent outside this app (Claude Code, Claude, another assistant) use the governed metrics as you, through the MCP
        server at <code>{url}</code>. It sees what you may see: aggregates with small counts hidden, never rows about a person.
      </p>
      <form className="card controls" onSubmit={create}>
        <label>
          Name
          <input name="name" required maxLength={80} placeholder="e.g. Claude Code on my laptop" />
        </label>
        <label>
          Expires after
          <select name="days" defaultValue={list?.expiry_days.includes(90) ? 90 : list?.expiry_days[0]}>
            {(list?.expiry_days ?? [90]).map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Create token</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {made && (
        <div className="card made" role="status">
          <p>
            <strong>Copy this token now.</strong> It will not be shown again.
          </p>
          <pre>{made}</pre>
          <button onClick={() => void navigator.clipboard?.writeText(made)}>Copy</button>{' '}
          <button className="link" onClick={() => setMade(null)}>
            Done
          </button>
          <p className="note">For Claude Code, put it in an environment variable (BI_TOKEN) and add to <code>.mcp.json</code>:</p>
          <pre>{config}</pre>
        </div>
      )}
      {user.is_admin && (
        <label className="inline">
          <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} /> Show everyone&apos;s tokens
        </label>
      )}
      {list && list.tokens.length === 0 && <p className="hint">No tokens yet.</p>}
      {list && list.tokens.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              {everyone && <th>Owner</th>}
              <th>Starts with</th>
              <th>Created</th>
              <th>Expires</th>
              <th>Last used</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.tokens.map((t) => (
              <tr key={t.id}>
                <td dir="auto">{t.name}</td>
                {everyone && <td>{t.owner}</td>}
                <td>
                  <code>{t.hint}…</code>
                </td>
                <td>{date(t.created_at)}</td>
                <td>{date(t.expires_at)}</td>
                <td>{date(t.last_used_at)}</td>
                <td>{status(t)}</td>
                <td>
                  {status(t) === 'active' && (
                    <button className="link" onClick={() => void revoke(t)}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
