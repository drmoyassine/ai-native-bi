import { label, number, toEcharts, type ChartDefinition, type GovernedMember, type Row } from './chart';
import { EChart } from './EChart';

/** A chart definition drawn from its rows: ECharts for bar, line and pie; a number and a table drawn here. Used by the chart page and the chat. */
export function ChartView({ definition, rows, members }: { definition: ChartDefinition; rows: Row[]; members: GovernedMember[] }) {
  const { type } = definition.visual;
  const option = toEcharts(definition, rows, members);
  const first = definition.query.measures[0] ?? '';
  const dimensions = definition.query.dimensions ?? [];
  return (
    <>
      {option && <EChart option={option} />}
      {type === 'number' && (
        <figure className="number">
          <figcaption>{definition.title}</figcaption>
          <strong>{number(rows[0]?.[first])?.toLocaleString() ?? '—'}</strong>
        </figure>
      )}
      {type === 'table' && (
        <table>
          <thead>
            <tr>
              {[...dimensions, ...definition.query.measures].map((m) => (
                <th key={m}>{members.find((x) => x.name === m)?.title ?? m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {dimensions.map((d) => (
                  <td key={d}>{label(r[d])}</td>
                ))}
                {definition.query.measures.map((m) => (
                  <td key={m} className="num">
                    {number(r[m])?.toLocaleString() ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
