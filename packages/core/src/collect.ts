import { createHash, timingSafeEqual } from 'node:crypto';
import type pg from 'pg';
import { CollectRequestSchema, type CollectRequest } from '@bi/contract';

/** Constant-time check of the AMS's bearer key. */
export function keyMatches(header: string | undefined, key: string): boolean {
  const given = header?.match(/^Bearer (.+)$/)?.[1] ?? '';
  const a = createHash('sha256').update(given).digest();
  const b = createHash('sha256').update(key).digest();
  return given.length > 0 && timingSafeEqual(a, b);
}

export type Accepted = { ok: true; id: string; repeat: boolean } | { ok: false; status: 400 | 422; issues: { path: string; message: string }[] };

/**
 * Takes one request of the AMS (contract 3.6) and keeps it for the worker. The callback address must be on the AMS's origin and be
 * the run's own supply route, so a caller cannot make the BI post anywhere else. The same attempt sent twice is kept once.
 */
export async function acceptCollect(pool: pg.Pool, body: unknown, amsOrigin: string): Promise<Accepted> {
  const parsed = CollectRequestSchema.safeParse(body);
  if (!parsed.success) return { ok: false, status: 422, issues: parsed.error.issues.map((i) => ({ path: i.path.join('.'), message: i.message })) };
  const req: CollectRequest = parsed.data;
  const cb = new URL(req.callbackUrl);
  const expected = `/api/bi/v0/runs/${encodeURIComponent(req.runId)}/supply`;
  if (cb.origin !== amsOrigin || !cb.pathname.endsWith(expected) || cb.search || cb.hash) {
    return { ok: false, status: 422, issues: [{ path: 'callbackUrl', message: `the callback must be ${amsOrigin}...${expected}` }] };
  }
  const tokenHash = createHash('sha256').update(req.callbackToken).digest('hex');
  const stored = { ...req, callbackToken: undefined };
  const r = await pool.query<{ id: string; inserted: boolean }>(
    `insert into collect_request (run_id, token_hash, callback_token, callback_url, request) values ($1, $2, $3, $4, $5)
     on conflict (run_id, token_hash) do update set run_id = excluded.run_id
     returning id, (xmax = 0) as inserted`,
    [req.runId, tokenHash, req.callbackToken, req.callbackUrl, JSON.stringify(stored)],
  );
  const row = r.rows[0]!;
  return { ok: true, id: row.id, repeat: !row.inserted };
}
