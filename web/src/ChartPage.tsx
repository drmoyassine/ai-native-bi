import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import type { ChartDefinition, ChartType, GovernedMember, Row } from './chart';
import { ChartView } from './ChartView';

const TYPES: ChartType[] = ['bar', 'line', 'pie', 'table', 'number'];

/** The first chart: a governed measure by a governed dimension. It builds a chart definition (DEC-012), as the agent and the
 * drag-and-drop builder will; the server checks it against Cube and answers its rows. */
export function ChartPage() {
  const [members, setMembers] = useState<GovernedMember[]>([]);
  const [measure, setMeasure] = useState('');
  const [dimension, setDimension] = useState('');
  const [type, setType] = useState<ChartType>('bar');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ members: GovernedMember[] }>('/members')
      .then(({ members }) => {
        setMembers(members);
        setMeasure(members.find((m) => m.kind === 'measure')?.name ?? '');
        setDimension(members.find((m) => m.kind === 'dimension' && m.type !== 'time')?.name ?? '');
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const measures = members.filter((m) => m.kind === 'measure');
  const dimensions = members.filter((m) => m.kind === 'dimension' && m.type !== 'time');
  const byDimension = type !== 'number' && dimension !== '';

  const definition = useMemo<ChartDefinition | null>(() => {
    if (!measure) return null;
    const title = (name: string) => members.find((m) => m.name === name)?.title ?? name;
    return {
      version: 1,
      title: byDimension ? `${title(measure)} by ${title(dimension).toLowerCase()}` : title(measure),
      query: { measures: [measure], dimensions: byDimension ? [dimension] : [] },
      visual: { type, ...(byDimension && type !== 'table' ? { x: dimension } : {}) },
    };
  }, [measure, dimension, type, byDimension, members]);

  useEffect(() => {
    if (!definition) return;
    setRows(null);
    setError(null);
    api
      .post<{ rows: Row[] }>('/charts/data', definition)
      .then(({ rows }) => setRows(rows))
      .catch((err: Error) => setError(err.message));
  }, [definition]);

  return (
    <section>
      <h2>Chart</h2>
      <div className="card controls">
        <label>
          Measure
          <select value={measure} onChange={(e) => setMeasure(e.target.value)}>
            {measures.map((m) => (
              <option key={m.name} value={m.name} title={m.description ?? ''}>
                {m.cube ? `${m.cube}: ` : ''}
                {m.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          By
          <select value={dimension} onChange={(e) => setDimension(e.target.value)} disabled={type === 'number'}>
            {dimensions.map((d) => (
              <option key={d.name} value={d.name}>
                {d.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          As
          <select value={type} onChange={(e) => setType(e.target.value as ChartType)}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {rows && rows.length === 0 && <p className="hint">No data: nothing has been loaded for this yet.</p>}
      {definition && rows && rows.length > 0 && (
        <div className="card">
          <ChartView definition={definition} rows={rows} members={members} />
        </div>
      )}
      {definition && (
        <details>
          <summary>Chart definition</summary>
          <pre>{JSON.stringify(definition, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
