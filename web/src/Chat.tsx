import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { api, type ConversationSummary, type ModelGroup, type Usage } from './api';
import { apply, stopNote, type AgentEvent, type ChatState, type Item } from './agentEvents';
import type { ChartDefinition, GovernedMember, Row } from './chart';
import { ChartView } from './ChartView';

const EVENT_TYPES = [
  'turn.started',
  'text.delta',
  'tool.started',
  'tool.finished',
  'result.table',
  'result.chart',
  'turn.finished',
  'turn.failed',
];
const EMPTY: ChatState = { items: [], end: null };

const TOOL_LABELS: Record<string, string> = {
  list_metrics: 'Looking up the governed metrics',
  query_metric: 'Querying a metric',
  propose_chart: 'Preparing a chart',
  list_datasets: 'Listing the datasets',
  describe_dataset: 'Describing a dataset',
};

const tokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${Math.round(n / 1_000)}k` : String(n));

/** Ask questions in plain words; the answer comes with the governed numbers behind it, as tables and charts. */
export function Chat() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<string | 'new'>('new');
  const [members, setMembers] = useState<GovernedMember[]>([]);

  const refresh = useCallback(async () => {
    setConversations((await api.get<{ conversations: ConversationSummary[] }>('/conversations')).conversations);
  }, []);

  useEffect(() => {
    void refresh();
    api
      .get<{ members: GovernedMember[] }>('/members')
      .then((r) => setMembers(r.members))
      .catch(() => setMembers([])); // charts then show the raw names; the chat itself still works
  }, [refresh]);

  return (
    <div className="chat">
      <aside aria-label="Conversations">
        <button className={selected === 'new' ? 'active' : ''} onClick={() => setSelected('new')}>
          + New conversation
        </button>
        <ul>
          {conversations.map((c) => (
            <li key={c.id}>
              <button
                className={selected === c.id ? 'active' : ''}
                onClick={() => setSelected(c.id)}
                title={`${c.provider} · ${c.model_id}`}
              >
                <span dir="auto">{c.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="thread-pane">
        {selected === 'new' ? (
          <NewChat
            onStarted={async (id) => {
              await refresh();
              setSelected(id);
            }}
          />
        ) : (
          <Thread key={selected} id={selected} members={members} onTitle={() => void refresh()} />
        )}
      </section>
    </div>
  );
}

function NewChat({ onStarted }: { onStarted: (id: string) => Promise<void> }) {
  const [groups, setGroups] = useState<ModelGroup[] | null>(null);
  const [choice, setChoice] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ providers: ModelGroup[] }>('/models?mode=ask')
      .then(({ providers }) => {
        setGroups(providers);
        const preferred =
          providers.flatMap((g) => g.models.map((m) => ({ g, m }))).find((x) => x.m.default) ??
          providers.flatMap((g) => g.models.map((m) => ({ g, m })))[0];
        if (preferred) setChoice(`${preferred.g.provider_id}\n${preferred.m.model_id}`);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const selected = useMemo(() => {
    const [pid, mid] = choice.split('\n');
    const g = groups?.find((x) => x.provider_id === pid);
    return g ? { g, m: g.models.find((m) => m.model_id === mid) } : null;
  }, [choice, groups]);

  async function start(e: FormEvent) {
    e.preventDefault();
    const [provider_id, model_id] = choice.split('\n');
    try {
      const { id } = await api.post<{ id: string }>('/conversations', { mode: 'ask', provider_id, model_id });
      await onStarted(id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="card new-chat" onSubmit={start}>
      <h2>New conversation</h2>
      {groups && groups.length === 0 && (
        <p className="hint">No model is available yet. An admin adds a provider and allows its models under Models.</p>
      )}
      {groups && groups.length > 0 && (
        <>
          <label>
            Model
            <select value={choice} onChange={(e) => setChoice(e.target.value)}>
              {groups.map((g) => (
                <optgroup key={g.provider_id} label={g.provider}>
                  {g.models.map((m) => (
                    <option key={m.model_id} value={`${g.provider_id}\n${m.model_id}`}>
                      {m.name}
                      {m.default ? ' (default)' : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          {selected && (
            <p className="note">
              {selected.m?.context_window ? `${tokens(selected.m.context_window)} tokens of context. ` : ''}
              {selected.g.data_path}
            </p>
          )}
          <button type="submit">Start</button>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

function Thread({ id, members, onTitle }: { id: string; members: GovernedMember[]; onTitle: () => void }) {
  const [state, setState] = useState<ChatState>(EMPTY);
  const [model, setModel] = useState('');
  const [running, setRunning] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const source = useRef<EventSource | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshUsage = useCallback(() => {
    api
      .get<Usage>('/agent/usage')
      .then(setUsage)
      .catch(() => setUsage(null));
  }, []);

  /** Follows a turn from an event id on; ends when the server says nothing more is coming. */
  const follow = useCallback(
    (after: number) => {
      source.current?.close();
      setRunning(true);
      const es = new EventSource(`/app/api/conversations/${id}/events?after=${after}`);
      source.current = es;
      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (raw) => {
          const payload = JSON.parse((raw as MessageEvent<string>).data) as Record<string, unknown>;
          const event: AgentEvent = { id: Number((raw as MessageEvent).lastEventId), type, payload };
          setState((s) => apply(s, event));
        });
      }
      es.addEventListener('end', () => {
        es.close();
        setRunning(false);
        refreshUsage();
        onTitle();
      });
      // Not an `end`: the connection dropped. The browser reconnects by itself with Last-Event-ID; nothing to do here.
    },
    [id, onTitle, refreshUsage],
  );

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ conversation: { model_id: string }; items: Item[]; active_run: unknown; last_event_id: number }>(`/conversations/${id}`)
      .then((c) => {
        if (cancelled) return;
        setState({ items: c.items, end: null });
        setModel(c.conversation.model_id);
        if (c.active_run) follow(c.last_event_id);
      })
      .catch((err: Error) => setError(err.message));
    refreshUsage();
    return () => {
      cancelled = true;
      source.current?.close();
    };
  }, [id, follow, refreshUsage]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' });
  }, [state.items, state.end]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const message = text.trim();
    if (!message || running) return;
    setError(null);
    try {
      const { after } = await api.post<{ run_id: string; after: number }>(`/conversations/${id}/messages`, { text: message });
      setText('');
      setState((s) => ({ items: [...s.items, { kind: 'user', text: message }], end: null }));
      follow(after);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const over = usage && (usage.person.used >= usage.person.cap || usage.organization.used >= usage.organization.cap);

  return (
    <>
      <div className="thread" aria-live="polite">
        {state.items.length === 0 && !running && (
          <p className="hint">Ask about the data, for example “What are the latest figures, by month?”</p>
        )}
        {state.items.map((item, i) => (
          <Message key={i} item={item} members={members} />
        ))}
        {running && <p className="hint working">Working…</p>}
        {state.end && stopNote(state.end) && (
          <p className={state.end.failed ? 'error' : 'hint'} role={state.end.failed ? 'alert' : undefined}>
            {stopNote(state.end)}
          </p>
        )}
        <div ref={bottom} />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form className="composer" onSubmit={send}>
        <textarea
          dir="auto"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) void send(e);
          }}
          placeholder="Ask a question…"
          rows={2}
          aria-label="Your question"
        />
        {running ? (
          <button type="button" onClick={() => void api.post(`/conversations/${id}/interrupt`)}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!text.trim() || !!over}>
            Send
          </button>
        )}
      </form>
      <p className="note usage">
        {model}
        {usage && ` · you ${tokens(usage.person.used)} of ${tokens(usage.person.cap)} tokens this month`}
        {over && ' · the monthly budget is used up; an admin can raise it'}
      </p>
    </>
  );
}

function Message({ item, members }: { item: Item; members: GovernedMember[] }) {
  switch (item.kind) {
    case 'user':
      return (
        <p className="bubble user" dir="auto">
          {item.text}
        </p>
      );
    case 'assistant':
      return (
        <p className="bubble assistant" dir="auto">
          {item.text}
        </p>
      );
    case 'tool':
      return (
        <p className={`tool ${item.ok === false ? 'failed' : ''}`} title={item.args}>
          {item.ok === null ? '⏳' : item.ok ? '✓' : '✗'} {TOOL_LABELS[item.name] ?? item.name}
          {item.summary ? ` — ${item.summary}` : ''}
        </p>
      );
    case 'table': {
      const definition: ChartDefinition = { version: 1, title: '', query: item.query, visual: { type: 'table' } };
      return (
        <div className="card result">
          {item.rows.length === 0 ? (
            <p className="hint">No data: nothing has been loaded for this yet.</p>
          ) : (
            <ChartView definition={definition} rows={item.rows} members={members} />
          )}
          <p className="note">
            {item.row_count} row{item.row_count === 1 ? '' : 's'}
            {item.as_of ? ` · data as of ${item.as_of}` : ''}
            {item.suppressed_cells > 0
              ? ` · ${item.suppressed_cells} small count${item.suppressed_cells === 1 ? '' : 's'} hidden to protect privacy`
              : ''}
          </p>
        </div>
      );
    }
    case 'chart':
      return <ProposedChart draftId={item.draft_id} chart={item.chart} members={members} />;
  }
}

/** The agent proposes a chart definition, never a picture: the data comes from the governed read, like the chart page's. */
function ProposedChart({ draftId, chart, members }: { draftId: string | null; chart: ChartDefinition; members: GovernedMember[] }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [hidden, setHidden] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    // The draft's own data route: small counts are hidden there, as they were for the model.
    api
      .get<{ rows: Row[]; suppressed_cells: number }>(`/drafts/${draftId}/data`)
      .then((r) => {
        setRows(r.rows);
        setHidden(r.suppressed_cells);
      })
      .catch((err: Error) => setError(err.message));
  }, [draftId]);
  return (
    <div className="card result">
      <p className="note">Proposed chart · a draft until a person publishes it</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!rows && !error && <p className="hint">Loading…</p>}
      {rows && rows.length === 0 && <p className="hint">No data: nothing has been loaded for this yet.</p>}
      {rows && rows.length > 0 && <ChartView definition={chart} rows={rows} members={members} />}
      {hidden > 0 && (
        <p className="note">
          {hidden} small count{hidden === 1 ? '' : 's'} hidden to protect privacy
        </p>
      )}
    </div>
  );
}
