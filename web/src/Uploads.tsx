import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Upload } from './api';

const today = () => new Date().toISOString().slice(0, 10);

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
