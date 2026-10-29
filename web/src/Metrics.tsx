import { useEffect, useState } from 'react';
import { api } from './api';

interface Words {
  title?: string;
  description?: string;
}

interface Member {
  name: string;
  title: string;
  kind: 'measure' | 'dimension';
  description?: string;
  cube?: string;
  ar?: Words;
  synonyms?: { en?: string[]; ar?: string[] };
  knowledge?: { en?: string; ar?: string };
  metric?: string;
}

interface Term {
  term: string;
  ar?: string;
  en?: string;
  ar_meaning?: string;
}

interface Knowledge {
  members: Member[];
  glossary: Term[];
  instructions: string[];
}

// The institution's metric definitions with their words in both languages, read from the Cube model (docs/context-spec.md section 4).
// Read-only: a definition changes by pull request, which a steward approves.
export function Metrics() {
  const [query, setQuery] = useState('');
  const [data, setData] = useState<Knowledge | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .get<Knowledge>(`/knowledge${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ''}`)
        .then((d) => {
          setData(d);
          setError('');
        })
        .catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <section>
      <h2>Metrics</h2>
      <p className="hint">
        What the organization measures and what each word means, in its languages. This is the definition the chat, the MCP server and
        the AMS all read. To change one, propose the edit to its steward; it goes live when the pull request is merged.
      </p>
      <input placeholder="Search by any word or synonym, in English or Arabic" value={query} onChange={(e) => setQuery(e.target.value)} />
      {error && <p className="error">{error}</p>}
      {data && data.members.length === 0 && <p className="hint">Nothing matches.</p>}
      {data?.members.map((m) => (
        <div className="card" key={m.name} style={{ marginTop: 12 }}>
          <strong>{m.title}</strong>{' '}
          <span className="hint">
            {m.kind}
            {m.metric ? ` · exposed to the AMS as ${m.metric}` : ''} · {m.name}
          </span>
          {m.ar?.title && (
            <div dir="rtl" lang="ar">
              {m.ar.title}
            </div>
          )}
          {m.description && <p>{m.description}</p>}
          {m.ar?.description && (
            <p dir="rtl" lang="ar">
              {m.ar.description}
            </p>
          )}
          {m.synonyms && <p className="hint">Also called: {[...(m.synonyms.en ?? []), ...(m.synonyms.ar ?? [])].join(', ')}</p>}
          {m.knowledge?.en && <p className="note">{m.knowledge.en}</p>}
          {m.knowledge?.ar && (
            <p className="note" dir="rtl" lang="ar">
              {m.knowledge.ar}
            </p>
          )}
        </div>
      ))}
      {data && data.glossary.length > 0 && (
        <>
          <h3>Glossary</h3>
          {data.glossary.map((g) => (
            <p key={g.term}>
              <strong>{g.term}</strong>
              {g.ar && <span lang="ar"> ({g.ar})</span>}: {g.en} {g.ar_meaning && <span lang="ar">{g.ar_meaning}</span>}
            </p>
          ))}
        </>
      )}
      {data && data.instructions.length > 0 && (
        <>
          <h3>Instructions every assistant follows</h3>
          <ul>
            {data.instructions.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
