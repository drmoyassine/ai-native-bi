import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type ColumnMapping, type Upload } from './api';

const today = () => new Date().toISOString().slice(0, 10);

// The columns found in the files of a dataset, matched to what the dataset needs; a person confirms the match (or fixes it).
function Mapping({ dataset, version, onDone }: { dataset: string; version: string; onDone: () => void }) {
  const [state, setState] = useState<ColumnMapping | null>(null);
  const [choice, setChoice] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.get<ColumnMapping>(`/datasets/${dataset}/mapping`).then((m) => {
      setState(m);
      setChoice(m.mapping);
    });
  }, [dataset, version]);

  if (!state || state.parts.length === 0 || state.columns.length === 0) return null;
  const missing = state.parts.filter((p) => p.required && !choice[p.name]);

  async function approve() {
    setError(null);
    try {
      await api.put(`/datasets/${dataset}/mapping`, { mapping: choice });
      setState({ ...state!, status: 'approved' });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="card">
      <h3>Columns of {dataset}</h3>
      <p className="note">
        {state.status === 'approved'
          ? 'Approved. Change a choice to rebuild the analytics from other columns.'
          : 'These are the columns the files have. Check which one plays which part, then approve to build the analytics.'}
      </p>
      <table>
        <tbody>
          {state.parts.map((p) => (
            <tr key={p.name}>
              <td>
                {p.name}
                {p.required ? ' *' : ''}
              </td>
              <td>
                <select
                  value={choice[p.name] ?? ''}
                  onChange={(e) => setChoice({ ...choice, [p.name]: e.target.value || null })}
                  aria-label={p.name}
                >
                  <option value="">(none)</option>
                  {state.columns.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {state.error && <p className="error">The last build failed: {state.error}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <button type="button" onClick={() => void approve()} disabled={missing.length > 0}>
        {state.status === 'approved' ? 'Rebuild' : 'Approve and build'}
      </button>
      {missing.length > 0 && <span className="hint"> Needed: {missing.map((p) => p.name).join(', ')}</span>}
    </div>
  );
}

export function Uploads({ datasets }: { datasets: string[] }) {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setUploads((await api.get<{ uploads: Upload[] }>('/uploads')).uploads);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While a load is waiting or running, look again every few seconds.
  const pending = uploads.some((u) => u.status === 'queued' || u.status === 'running');
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [pending, refresh]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError(null);
    try {
      await api.post('/uploads', new FormData(form));
      form.reset();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Upload a file</h2>
      <p className="note">
        Test files only until the privacy rules are set (ROADMAP-008). The file is kept unchanged; its rows are loaded and the
        analytics rebuilt, with their tests.
      </p>
      <form onSubmit={submit} className="card upload">
        <label>
          File (.xlsx, .xlsb, .xls, .ods, .csv)
          <input name="file" type="file" accept=".xlsx,.xlsm,.xlsb,.xls,.ods,.csv" required />
        </label>
        <label>
          Dataset
          <select name="dataset" required>
            {datasets.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
        <label>
          True as of
          <input name="asOf" type="date" max={today()} required />
        </label>
        <label>
          Sheet <span className="hint">(default: the first)</span>
          <input name="sheet" type="text" />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Uploading…' : 'Upload'}
        </button>
      </form>

      {datasets.map((d) => (
        <Mapping key={d} dataset={d} version={uploads.map((u) => u.status).join()} onDone={() => void refresh()} />
      ))}

      <h2>Uploads</h2>
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Dataset</th>
            <th>As of</th>
            <th>Status</th>
            <th>Rows</th>
            <th>Tests</th>
            <th>By</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {uploads.map((u) => (
            <tr key={u.id}>
              <td>{u.file_name}</td>
              <td>{u.dataset}</td>
              <td>{u.as_of}</td>
              <td>
                <span className={`status ${u.status}`}>{u.status}</span>
                {u.repeat && <span className="hint"> (already loaded)</span>}
                {u.error && <div className="error">{u.error}</div>}
                {u.note && <div className="hint">{u.note}</div>}
              </td>
              <td>{u.rows ?? ''}</td>
              <td>{u.tests ?? ''}</td>
              <td>{u.name}</td>
              <td>{new Date(u.created_at).toLocaleString()}</td>
            </tr>
          ))}
          {uploads.length === 0 && (
            <tr>
              <td colSpan={8} className="hint">
                No uploads yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
