// The chart definition, version 1 (DEC-012; the server's schema is src/bi/charts.py), and the one translator from a definition and its
// rows to ECharts options. Neither the agent nor the API ever writes ECharts options: they write a definition.
import type { EChartsCoreOption } from 'echarts/core';

export type Member = string;
export type ChartType = 'bar' | 'line' | 'pie' | 'table' | 'number';

export interface ChartDefinition {
  version: 1;
  title: string;
  query: {
    measures: Member[];
    dimensions?: Member[];
    filters?: { member: Member; operator: 'equals' | 'notEquals' | 'gt' | 'gte' | 'lt' | 'lte'; values: string[] }[];
    time?: { dimension: Member; dateRange?: [string, string]; granularity?: 'day' | 'week' | 'month' | 'quarter' | 'year' };
  };
  visual: { type: ChartType; x?: Member; series?: Member };
}

/** A governed field as Cube describes it (GET /app/api/members). */
export interface GovernedMember {
  name: Member;
  title: string;
  kind: 'measure' | 'dimension';
  type: string | null;
  description?: string | null;
  cube?: string;
}

export type Row = Record<string, string | number | boolean | null>;

const title = (members: GovernedMember[], name: Member): string => members.find((m) => m.name === name)?.title ?? name;

/** Cube answers numbers as text; a cell that is not a number stays null (never made up). */
export function number(value: Row[string] | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** A category label: dates from Cube (2026-08-24T00:00:00.000) shown as dates. */
export function label(value: Row[string] | undefined): string {
  if (value === null || value === undefined) return '(none)';
  const s = String(value);
  return /^\d{4}-\d{2}-\d{2}T00:00:00(\.000)?$/.test(s) ? s.slice(0, 10) : s;
}

/** ECharts options for a bar, line or pie chart; null for a table or a number, which are not drawn by ECharts. */
export function toEcharts(def: ChartDefinition, rows: Row[], members: GovernedMember[]): EChartsCoreOption | null {
  const { type, x, series } = def.visual;
  if (type === 'table' || type === 'number' || !x) return null;
  const categories = [...new Set(rows.map((r) => label(r[x])))];
  if (type === 'pie') {
    const measure = def.query.measures[0]!;
    return {
      title: { text: def.title, left: 'center' },
      tooltip: { trigger: 'item' },
      series: [{ type: 'pie', name: title(members, measure), radius: '60%', data: rows.map((r) => ({ name: label(r[x]), value: number(r[measure]) })) }],
    };
  }
  const value = (r: Row | undefined, m: Member) => (r ? number(r[m]) : null);
  const lines = series
    ? [...new Set(rows.map((r) => label(r[series])))].map((s) => ({
        type,
        name: s,
        data: categories.map((c) => value(rows.find((r) => label(r[x]) === c && label(r[series]) === s), def.query.measures[0]!)),
      }))
    : def.query.measures.map((m) => ({ type, name: title(members, m), data: categories.map((c) => value(rows.find((r) => label(r[x]) === c), m)) }));
  const counts = lines.every((l) => l.data.every((v) => v === null || Number.isInteger(v)));
  return {
    title: { text: def.title },
    tooltip: { trigger: 'axis' },
    ...(lines.length > 1 ? { legend: { top: 32 } } : {}),
    grid: { top: lines.length > 1 ? 72 : 56, left: 48, right: 24, bottom: 56 },
    xAxis: { type: 'category', name: title(members, x), nameLocation: 'middle', nameGap: 32, data: categories },
    yAxis: { type: 'value', ...(counts ? { minInterval: 1 } : {}) },
    series: lines,
  };
}
