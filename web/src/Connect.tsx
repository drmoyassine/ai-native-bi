import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Reason, type Review, type Source, type SourceSummary, type SourceType, type Sync, type SyncStatus, type User } from './api';

// Connect data (docs/connect-data-spec.md): the institution's sources, a file being one type among several. A source is made, its data
// sent or synced, what was found is checked, and a BI admin approves before anything reaches the analytics.

const today = () => new Date().toISOString().slice(0, 10);

const STATUS: Record<SyncStatus, string> = {
  queued: 'Waiting',
  running: 'Reading…',
  review: 'Needs review',
  loaded: 'Loaded',
  failed: 'Failed',
  stale: 'Load again',
};

interface Listing {
  sources: SourceSummary[];
  types: SourceType[];
  datasets: { name: string; label: string }[];
}

export function Connect({ user }: { user: User }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [view, setView] = useState<{ kind: 'list' } | { kind: 'add' } | { kind: 'source'; id: string }>({ kind: 'list' });

  const refresh = useCallback(async () => setListing(await api.get<Listing>('/sources')), []);
  useEffect(() => {
    void refresh();
  }, [refresh, view]);

  if (!listing) return <p className="hint">Loading…</p>;
  const typeLabel = (t: string) => listing.types.find((x) => x.type === t)?.label ?? t;
  const datasetLabel = (d: string | null) => (d ? (listing.datasets.find((x) => x.name === d)?.label ?? d) : 'Kept as raw data only');

  if (view.kind === 'add')
    return <AddSource listing={listing} onCancel={() => setView({ kind: 'list' })} onMade={(id) => setView({ kind: 'source', id })} />;
  if (view.kind === 'source')
    return (
      <SourcePage id={view.id} user={user} typeLabel={typeLabel} datasetLabel={datasetLabel} onBack={() => setView({ kind: 'list' })} />
    );

  return (
    <section>
      <div className="page-head">
        <h1>Connect data</h1>
        <button type="submit" onClick={() => setView({ kind: 'add' })}>
          Add a source
        </button>
      </div>
      <p className="note">
        Each source is a place the institution&apos;s data comes from: exports you upload today, and databases, folders and other systems as
        they are added. Nothing reaches the analytics until a BI admin approves it.
      </p>
      {listing.sources.length === 0 ? (
        <div className="card empty">
          <p>No sources yet.</p>
          <p className="hint">Add one: for an export someone downloads, choose File.</p>
        </div>
      ) : (
        <div className="sources">
          {listing.sources.map((s) => (
            <button key={s.id} className="card source-card" onClick={() => setView({ kind: 'source', id: s.id })}>
              <span className="source-name">{s.name}</span>
              <span className="hint">
                {typeLabel(s.type)} · {datasetLabel(s.dataset)}
              </span>
              <span className="source-state">
                <span className={`badge ${s.state}`}>
                  {s.state === 'live' ? 'Live' : s.state === 'draft' ? 'Not approved yet' : 'Paused'}
                </span>
                {s.waiting > 0 && <span className="badge review">{s.waiting} to review</span>}
                {s.last_status && s.waiting === 0 && <span className={`status ${s.last_status}`}>{STATUS[s.last_status]}</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function AddSource({ listing, onCancel, onMade }: { listing: Listing; onCancel: () => void; onMade: (id: string) => void }) {
  const [type, setType] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError(null);
    try {
      const dataset = String(form.get('dataset') ?? '');
      const made = await api.post<{ id: string }>('/sources', {
        name: form.get('name'),
        type,
        dataset: dataset || null,
      });
      onMade(made.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section>
      <button className="link" onClick={onCancel}>
        ← Connect data
      </button>
      <h1>Add a source</h1>
      <h2>1. What kind of source?</h2>
      <div className="types">
        {listing.types.map((t) => (
          <button
            key={t.type}
            className={`card type ${type === t.type ? 'chosen' : ''}`}
            disabled={!t.available}
            onClick={() => setType(t.type)}
          >
            <strong>{t.label}</strong>
            <span className="hint">{t.hint}</span>
            {!t.available && <span className="hint soon">Coming ({t.step})</span>}
          </button>
        ))}
      </div>
      {type && (
        <form onSubmit={submit} className="card add-form">
          <h2>2. Name it, and say what it feeds</h2>
          <label>
            Name
            <input name="name" required maxLength={80} placeholder="Registrar enrollment exports" />
          </label>
          <label>
            What its data is
            <select name="dataset" defaultValue={listing.datasets[0]?.name ?? ''}>
              {listing.datasets.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.label}: builds the {d.label.toLowerCase()} analytics
                </option>
              ))}
              <option value="">Something else: keep it as raw data only</option>
            </select>
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit">Add the source</button>
        </form>
      )}
    </section>
  );
}

function SourcePage(props: {
  id: string;
  user: User;
  typeLabel: (t: string) => string;
  datasetLabel: (d: string | null) => string;
  onBack: () => void;
}) {
  const { id, user, typeLabel, datasetLabel, onBack } = props;
  const [source, setSource] = useState<Source | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => setSource(await api.get<Source>(`/sources/${id}`)), [id]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While a sync is waiting or being read, look again every few seconds.
  const pending = source?.syncs.some((s) => s.status === 'queued' || s.status === 'running');
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [pending, refresh]);

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/sources/${id}/files`, new FormData(form));
      form.reset();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function again(syncId: string) {
    await api.post(`/syncs/${syncId}/again`);
    await refresh();
  }

  if (!source) return <p className="hint">Loading…</p>;
  const waiting = source.syncs.find((s) => s.status === 'review');
  const open = reviewing ?? waiting?.id ?? null;

  return (
    <section>
      <button className="link" onClick={onBack}>
        ← Connect data
      </button>
      <div className="page-head">
        <h1>{source.name}</h1>
        <span className={`badge ${source.state}`}>
          {source.state === 'live' ? `Live, approved by ${source.approved_by ?? 'the operator'}` : 'Not approved yet'}
        </span>
      </div>
      <p className="hint">
        {typeLabel(source.type)} · {datasetLabel(source.dataset)}
      </p>

      {source.type === 'file' && (
        <form onSubmit={send} className="card upload">
          <label>
            File (.xlsx, .xlsb, .xls, .ods, .csv)
            <input name="file" type="file" accept=".xlsx,.xlsm,.xlsb,.xls,.ods,.csv" required />
          </label>
          <label>
            True as of
            <input name="asOf" type="date" max={today()} required />
          </label>
          <label>
            Sheet <span className="hint">(default: the first)</span>
            <input name="sheet" type="text" />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy}>
            {busy ? 'Sending…' : 'Send the file'}
          </button>
        </form>
      )}

      {open && (
        <ReviewPanel
          key={open}
          syncId={open}
          user={user}
          onDone={() => {
            setReviewing(null);
            void refresh();
          }}
        />
      )}

      <h2>Files received</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>As of</th>
              <th>Status</th>
              <th className="num">Rows</th>
              <th>By</th>
              <th>When</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {source.syncs.map((s: Sync) => (
              <tr key={s.id} className={s.id === open ? 'chosen' : ''}>
                <td>{s.file_name}</td>
                <td>{s.as_of}</td>
                <td>
                  <span className={`status ${s.status}`}>{STATUS[s.status]}</span>
                  {s.repeat && <span className="hint"> (already loaded)</span>}
                  {s.status === 'loaded' && s.tests ? <div className="hint">{s.tests} checks passed</div> : null}
                  {s.error && <div className="error">{s.error}</div>}
                  {s.note && s.status !== 'review' && <div className="hint">{s.note}</div>}
                </td>
                <td className="num">{s.rows ?? ''}</td>
                <td>{s.by_name ?? ''}</td>
                <td>{new Date(s.created_at).toLocaleString()}</td>
                <td>
                  {s.status === 'review' && s.id !== open && (
                    <button className="link" onClick={() => setReviewing(s.id)}>
                      Review
                    </button>
                  )}
                  {(s.status === 'failed' || s.status === 'stale') && (
                    <button className="link" onClick={() => void again(s.id)}>
                      Load again
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {source.syncs.length === 0 && (
              <tr>
                <td colSpan={7} className="hint">
                  Nothing received yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const CONFIDENCE: Record<string, string> = { high: 'sure', medium: 'fairly sure', low: 'a guess' };

// What the setup agent did, in plain words: its state, the header row it suggests, and what it saw.
function AgentNote({ review, user, onAsk, onHeader }: { review: Review; user: User; onAsk: () => void; onHeader: (row: number) => void }) {
  const a = review.agent;
  if (!review.dataset) return null;
  if (!a)
    return user.is_admin ? (
      <p className="agent-note">
        <button className="link" onClick={onAsk}>
          Ask the agent to check this
        </button>
      </p>
    ) : null;
  if (a.state === 'queued' || a.state === 'running') return <p className="agent-note hint">The agent is checking which column is which…</p>;
  if (a.state === 'failed') return <p className="agent-note hint">{a.error} The suggestions below are from the rules.</p>;
  if (a.state === 'none')
    return (
      <p className="agent-note hint">
        {a.reason} The suggestions below are from the rules.{' '}
        {user.is_admin && !a.reason?.startsWith('This layout') && (
          <button className="link" onClick={onAsk}>
            Try again
          </button>
        )}
      </p>
    );
  const masked = Object.keys(a.sample?.masked ?? {}).length > 0;
  return (
    <div className="agent-note">
      <p>
        <strong>The agent checked this</strong> <span className="hint">({a.model})</span>
        {a.earlier ? (
          <span className="hint"> It looked at an earlier file with the same columns.</span>
        ) : a.sample ? (
          <span className="hint">
            {' '}
            It saw {a.sample.rows} sample rows{masked ? ', with names, emails and IDs replaced' : ''}.
          </span>
        ) : (
          <span className="hint"> It saw the column names and what each holds, no rows.</span>
        )}
      </p>
      {a.header && (
        <p>
          It thinks the column names are on <strong>row {a.header.row}</strong>: {a.header.reason}{' '}
          <button className="link" onClick={() => onHeader(a.header!.row)}>
            Read it again from there
          </button>
        </p>
      )}
      {(a.dropped?.length ?? 0) > 0 && <p className="hint">Not used: {a.dropped?.join('; ')}.</p>}
    </div>
  );
}

function ReasonLine({ reason, chosen }: { reason?: Reason; chosen: string | null | undefined }) {
  if (!reason || reason.by !== 'agent' || !reason.reason) return null;
  const stands = reason.column === chosen;
  return (
    <div className={`hint reason ${reason.confidence}`}>
      Agent ({CONFIDENCE[reason.confidence]}): {reason.reason}
      {reason.confidence === 'low' && reason.column && !stands && <> It suggested “{reason.column}”; choose it if you agree.</>}
    </div>
  );
}

function ReviewPanel({ syncId, user, onDone }: { syncId: string; user: User; onDone: () => void }) {
  const [review, setReview] = useState<Review | null>(null);
  const [choice, setChoice] = useState<Record<string, string | null>>({});
  const [headerRow, setHeaderRow] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.get<Review>(`/syncs/${syncId}/review`).then((r) => {
      setReview(r);
      setChoice(r.mapping ?? {});
      setHeaderRow(String(r.header.row ?? ''));
    });
  }, [syncId]);

  // While the setup agent is thinking, look again every few seconds.
  const thinking = review?.agent?.state === 'queued' || review?.agent?.state === 'running';
  useEffect(() => {
    if (!thinking) return;
    const timer = window.setInterval(() => {
      void api.get<Review>(`/syncs/${syncId}/review`).then((r) => {
        setReview(r);
        if (r.agent?.state !== 'queued' && r.agent?.state !== 'running') setChoice(r.mapping ?? {});
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [thinking, syncId]);

  if (!review || review.sync.status !== 'review') return null;
  const missing = review.parts.filter((p) => p.required && !choice[p.name]);
  const byName = Object.fromEntries(review.columns.map((c) => [c.name, c]));

  async function act(path: string, body?: unknown) {
    setError(null);
    try {
      await api.post(path, body);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="card review">
      <h2>Check what was found in {review.sync.file_name}</h2>
      <p className="note">{review.sync.note}</p>

      <h3>The table</h3>
      <p>
        The column names are on <strong>row {review.header.row}</strong>
        {review.header.guessed === false ? ' (as you chose)' : ''}; {review.sync.rows} rows of data below them.
        {(review.header.above_header?.length ?? 0) > 0 && (
          <span className="hint"> Above them, left out: “{review.header.above_header?.join(' · ')}”.</span>
        )}
      </p>
      <div className="controls">
        <label>
          Not right? The column names are on row
          <input type="number" min={1} value={headerRow} onChange={(e) => setHeaderRow(e.target.value)} />
        </label>
        <button onClick={() => void act(`/syncs/${syncId}/header`, { row: Number(headerRow) })} disabled={!headerRow}>
          Read it again
        </button>
      </div>

      <AgentNote review={review} user={user} onAsk={() => void act(`/syncs/${syncId}/ask-agent`)} onHeader={(row) => void act(`/syncs/${syncId}/header`, { row })} />

      <h3>The columns</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Column</th>
              <th>What it holds</th>
            </tr>
          </thead>
          <tbody>
            {review.columns.map((c) => (
              <tr key={c.name}>
                <td>
                  {c.header} {c.kind === 'personal' && <span className="badge personal">Personal data</span>}
                </td>
                <td className="hint">{c.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Personal data is never shown as values; it is used only if you choose it below.</p>

      {review.dataset && (
        <>
          <h3>Which column is which</h3>
          <table className="mapping">
            <tbody>
              {review.parts.map((p) => (
                <tr key={p.name}>
                  <td>
                    <strong>{p.label}</strong>
                    {p.required ? ' *' : ''}
                    <div className="hint">{p.description}</div>
                    <ReasonLine reason={review.reasons?.[p.name]} chosen={choice[p.name]} />
                  </td>
                  <td>
                    <select
                      aria-label={p.label}
                      value={choice[p.name] ?? ''}
                      onChange={(e) =>
                        setChoice({
                          ...choice,
                          [p.name]: e.target.value || null,
                        })
                      }
                    >
                      <option value="">{p.required ? '— choose a column —' : '(not in this file)'}</option>
                      {review.columns.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.header}
                        </option>
                      ))}
                    </select>
                    {choice[p.name] && <div className="hint">{byName[choice[p.name] as string]?.summary}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">* needed</p>
        </>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {user.is_admin ? (
        <button
          type="submit"
          disabled={missing.length > 0}
          onClick={() =>
            void act(`/syncs/${syncId}/approve`, {
              mapping: review.dataset ? choice : null,
            })
          }
        >
          {review.dataset ? 'Approve and build the analytics' : 'Approve the source'}
        </button>
      ) : (
        <p className="hint">A BI admin approves what is loaded.</p>
      )}
      {missing.length > 0 && <span className="hint"> Still needed: {missing.map((p) => p.label).join(', ')}</span>}
    </div>
  );
}
