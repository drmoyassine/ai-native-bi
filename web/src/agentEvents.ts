// What the chat shows, and how the server's events (src/bi/agent/store.py, turn.py, tools.py) change it. The same items come from a
// stored conversation (GET /conversations/{id}) and from the live stream, so a reload shows what the stream showed.
import type { ChartDefinition, Row } from './chart';

export interface TableData {
  rows: Row[];
  row_count: number;
  suppressed_cells: number;
  as_of: string | null;
  query: ChartDefinition['query'];
}

export type Item =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; text: string; live?: boolean }
  | { kind: 'tool'; name: string; args?: string; ok: boolean | null; summary: string | null }
  | ({ kind: 'table' } & TableData)
  | { kind: 'chart'; draft_id: string | null; chart: ChartDefinition };

export interface AgentEvent {
  id: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface RunEnd {
  failed: boolean;
  stopReason: string;
  error?: string;
  outputTokens: number;
  inputTokens: number;
}

export interface ChatState {
  items: Item[];
  end: RunEnd | null;
}

const last = (items: Item[]) => items[items.length - 1];

/** Applies one event. Text arrives in pieces: it extends the assistant item being written, or starts one after a tool or a table. */
export function apply(state: ChatState, event: AgentEvent): ChatState {
  const p = event.payload;
  const items = state.items.map((i) => (i.kind === 'assistant' && i.live ? { ...i, live: false } : i));
  switch (event.type) {
    case 'turn.started':
      return { items: state.items, end: null };
    case 'text.delta': {
      const tail = last(state.items);
      if (tail?.kind === 'assistant' && tail.live) {
        return { ...state, items: [...state.items.slice(0, -1), { ...tail, text: tail.text + String(p.text ?? '') }] };
      }
      return { ...state, items: [...items, { kind: 'assistant', text: String(p.text ?? ''), live: true }] };
    }
    case 'tool.started': {
      // A stream that starts mid-turn can meet a call the stored conversation already shows: it stays one item.
      const name = String(p.name);
      if (items.some((i) => i.kind === 'tool' && i.name === name && i.ok === null)) return { ...state, items };
      return { ...state, items: [...items, { kind: 'tool', name, args: String(p.summary ?? ''), ok: null, summary: null }] };
    }
    case 'tool.finished': {
      const name = String(p.name);
      let done = false;
      const next = items.map((i) => {
        if (!done && i.kind === 'tool' && i.name === name && i.ok === null) {
          done = true;
          return { ...i, ok: Boolean(p.ok), summary: String(p.summary ?? '') };
        }
        return i;
      });
      return { ...state, items: next };
    }
    case 'result.table':
      return { ...state, items: [...items, { kind: 'table', ...(p as unknown as TableData) }] };
    case 'result.chart':
      return { ...state, items: [...items, { kind: 'chart', draft_id: String(p.draft_id), chart: p.chart as ChartDefinition }] };
    case 'turn.finished':
    case 'turn.failed': {
      const usage = (p.usage ?? {}) as { input_tokens?: number; output_tokens?: number };
      return {
        items,
        end: {
          failed: event.type === 'turn.failed',
          stopReason: String(p.stop_reason ?? ''),
          error: p.error ? String(p.error) : undefined,
          inputTokens: usage.input_tokens ?? 0,
          outputTokens: usage.output_tokens ?? 0,
        },
      };
    }
    default:
      return { ...state, items };
  }
}

/** Why a run stopped, in words a person reads; null when it simply finished. */
export function stopNote(end: RunEnd): string | null {
  if (end.failed) return `The answer failed: ${end.error ?? 'the provider returned an error'}. Your conversation is intact; you can send the message again.`;
  switch (end.stopReason) {
    case 'interrupted':
      return 'Stopped.';
    case 'limit':
      return 'Stopped: this answer reached its size limit. Ask a narrower question, or say "continue".';
    case 'length':
      return 'The answer was cut off at the model’s output limit. Say "continue" to go on.';
    case 'content_filter':
      return 'The provider withheld part of the answer (its content filter).';
    default:
      return null;
  }
}
