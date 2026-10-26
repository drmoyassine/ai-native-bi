import { describe, expect, it } from 'vitest';
import { apply, stopNote, type AgentEvent, type ChatState } from './agentEvents';

const empty: ChatState = { items: [], end: null };
let n = 0;
const ev = (type: string, payload: Record<string, unknown> = {}): AgentEvent => ({ id: ++n, type, payload });
const run = (events: AgentEvent[], from: ChatState = empty) => events.reduce(apply, from);

describe('apply', () => {
  it('joins text pieces into one answer, and starts a new one after a tool', () => {
    const s = run([ev('turn.started'), ev('text.delta', { text: 'Let me ' }), ev('text.delta', { text: 'look.' }), ev('tool.started', { name: 'list_metrics' }), ev('text.delta', { text: 'Done.' })]);
    expect(s.items.map((i) => i.kind)).toEqual(['assistant', 'tool', 'assistant']);
    expect(s.items[0]).toMatchObject({ text: 'Let me look.' });
  });

  it('settles a tool call with its outcome', () => {
    const s = run([ev('tool.started', { name: 'query_metric', summary: '{}' }), ev('tool.finished', { name: 'query_metric', ok: false, summary: 'unknown member' })]);
    expect(s.items[0]).toMatchObject({ kind: 'tool', ok: false, summary: 'unknown member' });
  });

  it('does not show a call twice when the stream starts after the stored conversation already has it', () => {
    const stored: ChatState = { items: [{ kind: 'tool', name: 'list_datasets', ok: null, summary: null }], end: null };
    const s = run([ev('tool.started', { name: 'list_datasets' }), ev('tool.finished', { name: 'list_datasets', ok: true, summary: '2 datasets' })], stored);
    expect(s.items).toHaveLength(1);
    expect(s.items[0]).toMatchObject({ ok: true });
  });

  it('adds tables and proposed charts as they arrive', () => {
    const chart = { version: 1, title: 'T', query: { measures: ['a.b'] }, visual: { type: 'number' } };
    const s = run([ev('result.table', { rows: [], row_count: 0, suppressed_cells: 2, as_of: '2026-10-20', query: { measures: ['a.b'] } }), ev('result.chart', { draft_id: 'd1', chart })]);
    expect(s.items.map((i) => i.kind)).toEqual(['table', 'chart']);
    expect(s.items[0]).toMatchObject({ suppressed_cells: 2 });
  });

  it('records how a turn ended, and a new turn clears it', () => {
    const failed = run([ev('turn.failed', { stop_reason: 'failed', error: 'bad key', usage: { input_tokens: 5, output_tokens: 1 } })]);
    expect(failed.end).toMatchObject({ failed: true, error: 'bad key', inputTokens: 5 });
    expect(run([ev('turn.started')], failed).end).toBeNull();
  });
});

describe('stopNote', () => {
  const end = { failed: false, stopReason: 'end', inputTokens: 0, outputTokens: 0 };
  it('says nothing about a normal finish and explains the rest', () => {
    expect(stopNote(end)).toBeNull();
    expect(stopNote({ ...end, stopReason: 'interrupted' })).toBe('Stopped.');
    expect(stopNote({ ...end, stopReason: 'limit' })).toMatch(/size limit/);
    expect(stopNote({ ...end, failed: true, error: 'boom' })).toMatch(/boom/);
  });
});
