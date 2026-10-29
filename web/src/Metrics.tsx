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
  /** The member's words in languages other than English, by language code. */
  translations?: Record<string, Words>;
  synonyms?: Record<string, string[]>;
  knowledge?: Record<string, string>;
  metric?: string;
}

/** A glossary entry: the term and its meaning, each by language code. */
interface Term {
  term: Record<string, string>;
  meaning?: Record<string, string>;
}

const others = (words: Record<string, string> | undefined) => Object.entries(words ?? {}).filter(([code]) => code !== 'en');

interface Knowledge {
  members: Member[];
  glossary: Term[];
  instructions: string[];
}

// The organization's metric definitions with their words in each of its languages, read from the Cube model (docs/context-spec.md section 4).
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
        What the organization measures and what each word means, in its languages. This is the definition the chat, the MCP server and the
        AMS all read. To change one, propose the edit to its steward; it goes live when the pull request is merged.
      </p>
      <input
        placeholder="Search by any word or synonym, in any of the organization's languages"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      {data && data.members.length === 0 && <p className="hint">Nothing matches.</p>}
      {data?.members.map((m) => (
        <div className="card" key={m.name} style={{ marginTop: 12 }}>
          <strong>{m.title}</strong>{' '}
          <span className="hint">
            {m.kind}
            {m.metric ? ` · exposed to the AMS as ${m.metric}` : ''} · {m.name}
          </span>
          {Object.entries(m.translations ?? {}).map(([code, w]) =>
            w.title ? (
              <div key={code} dir="auto" lang={code}>
                {w.title}
              </div>
            ) : null,
          )}
          {m.description && <p>{m.description}</p>}
          {Object.entries(m.translations ?? {}).map(([code, w]) =>
            w.description ? (
              <p key={code} dir="auto" lang={code}>
                {w.description}
              </p>
            ) : null,
          )}
          {m.synonyms && <p className="hint">Also called: {Object.values(m.synonyms).flat().join(', ')}</p>}
          {m.knowledge?.en && <p className="note">{m.knowledge.en}</p>}
          {others(m.knowledge).map(([code, text]) => (
            <p key={code} className="note" dir="auto" lang={code}>
              {text}
            </p>
          ))}
        </div>
      ))}
      {data && data.glossary.length > 0 && (
        <>
          <h3>Glossary</h3>
          {data.glossary.map((g) => (
            <p key={g.term.en ?? Object.values(g.term)[0]}>
              <strong>{g.term.en ?? Object.values(g.term)[0]}</strong>
              {others(g.term).map(([code, t]) => (
                <span key={code} lang={code}>
                  {' '}
                  ({t})
                </span>
              ))}
              : {g.meaning?.en}{' '}
              {others(g.meaning).map(([code, t]) => (
                <span key={code} dir="auto" lang={code}>
                  {t}{' '}
                </span>
              ))}
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
