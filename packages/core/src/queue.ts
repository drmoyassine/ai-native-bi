import type pg from 'pg';
import type { CollectRequest } from '@bi/contract';
import { postSupply } from './callback.js';
import type { SourceRegistry } from './sources.js';

export const COLLECT_QUEUE = 'collect';

export interface CollectDeps {
  pool: pg.Pool;
  sources: SourceRegistry;
  callbackTimeoutMs: number;
  fetcher?: typeof fetch;
}

type Row = { run_id: string; callback_token: string | null; callback_url: string; request: CollectRequest; status: string };

/**
 * Works one request: find a source, ask it, call the AMS back. Outcomes are kept on the row. A request no source can answer is
 * `no_source` and the AMS is NOT called (its run stays requested and its owner sees it; the AMS's own retries ask again). A 401/409
 * from the AMS ends the request (`refused`). A network error throws, so the queue retries it.
 */
export async function processCollect(deps: CollectDeps, id: string): Promise<string> {
  const { pool } = deps;
  const claimed = await pool.query<Row>(
    `update collect_request set status = 'running', attempts = attempts + 1 where id = $1 and status in ('queued', 'running')
     returning run_id, callback_token, callback_url, request, status`, [id]);
  const row = claimed.rows[0];
  if (!row || !row.callback_token) return 'skipped';
  const end = (status: string, error: string | null) => pool.query(
    `update collect_request set status = $2, last_error = $3, finished_at = now(), callback_token = null where id = $1`, [id, status, error]);

  const source = deps.sources.find(row.request);
  if (!source) {
    await end('no_source', `no source answers metric "${row.request.query?.metric ?? '(none)'}"${row.request.endpoint ? ` at endpoint "${row.request.endpoint}"` : ''}`);
    return 'no_source';
  }
  const supply = await source.answer(row.request);
  const r = await postSupply(row.callback_url, row.callback_token, supply, deps.callbackTimeoutMs, deps.fetcher);
  if (r.status === 200) { await end('supplied', null); return 'supplied'; }
  if ('final' in r) { await end('refused', `the AMS answered ${r.status}`); return 'refused'; }
  if (r.status === 422) { await end('failed', `the AMS refused the supply: ${r.issues.map((i) => `${i.path}: ${i.message}`).join('; ')}`); return 'failed'; }
  await pool.query('update collect_request set last_error = $2 where id = $1', [id, r.message]);
  throw new Error(`callback failed: ${r.message}`);
}
