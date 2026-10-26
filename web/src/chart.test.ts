import { describe, expect, it } from 'vitest';
import { label, number, toEcharts, type ChartDefinition, type GovernedMember, type Row } from './chart';

const members: GovernedMember[] = [
  { name: 'enrollment.headcount', title: 'Headcount', kind: 'measure', type: 'number' },
  { name: 'enrollment.program', title: 'Program', kind: 'dimension', type: 'string' },
  { name: 'enrollment.level', title: 'Level', kind: 'dimension', type: 'string' },
];
const def = (visual: ChartDefinition['visual'], dimensions = ['enrollment.program']): ChartDefinition => ({
  version: 1,
  title: 'Headcount',
  query: { measures: ['enrollment.headcount'], dimensions },
  visual,
});
const rows: Row[] = [
  { 'enrollment.program': 'BSME', 'enrollment.level': 'bachelor', 'enrollment.headcount': '120' },
  { 'enrollment.program': 'BSCE', 'enrollment.level': 'bachelor', 'enrollment.headcount': '87' },
  { 'enrollment.program': 'MSDS', 'enrollment.level': 'master', 'enrollment.headcount': '20' },
];

describe('the chart translator', () => {
  it('reads Cube numbers and never makes one up', () => {
    expect([number('120'), number(3), number(null), number(''), number('n/a')]).toEqual([120, 3, null, null, null]);
    expect([label('2026-08-24T00:00:00.000'), label(null), label('BSME')]).toEqual(['2026-08-24', '(none)', 'BSME']);
  });

  it('draws a bar chart with the categories in Cube order and titled axes', () => {
    const option = toEcharts(def({ type: 'bar', x: 'enrollment.program' }), rows, members) as Record<string, any>;
    expect(option.xAxis).toMatchObject({ name: 'Program', data: ['BSME', 'BSCE', 'MSDS'] });
    expect(option.series).toEqual([{ type: 'bar', name: 'Headcount', data: [120, 87, 20] }]);
    expect(option.legend).toBeUndefined();
    expect(option.yAxis).toEqual({ type: 'value', minInterval: 1 });
  });

  it('lets a measure with fractions keep fractional steps', () => {
    const rates = rows.map((r) => ({ ...r, 'enrollment.headcount': '0.5' }));
    const option = toEcharts(def({ type: 'bar', x: 'enrollment.program' }), rates, members) as Record<string, any>;
    expect(option.yAxis).toEqual({ type: 'value' });
  });

  it('splits a measure into series, leaving a gap where there is no row', () => {
    const option = toEcharts(def({ type: 'line', x: 'enrollment.level', series: 'enrollment.program' }, ['enrollment.level', 'enrollment.program']), rows, members) as Record<string, any>;
    expect(option.xAxis.data).toEqual(['bachelor', 'master']);
    expect(option.series).toContainEqual({ type: 'line', name: 'MSDS', data: [null, 20] });
    expect(option.legend).toEqual({ top: 32 });
  });

  it('draws a pie, and leaves tables and numbers to the page', () => {
    const pie = toEcharts(def({ type: 'pie', x: 'enrollment.program' }), rows, members) as Record<string, any>;
    expect(pie.series[0].data[0]).toEqual({ name: 'BSME', value: 120 });
    expect(toEcharts(def({ type: 'table' }), rows, members)).toBeNull();
    expect(toEcharts(def({ type: 'number' }, []), rows, members)).toBeNull();
  });
});
