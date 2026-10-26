import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import pg from 'pg';
import type { CollectRequest, SupplyBody } from '@bi/contract';
import { acceptCollect, ensureDatabase, keyMatches, migrate, processCollect, SourceRegistry, type Source } from './index.js';

const ADMIN = process.env.TEST_DATABASE_ADMIN_URL!;
const DB_URL = (() => { const u = new URL(ADMIN); u.username = 'bi_test'; u.password = 'bi_test_pw'; u.pathname = '/bi_test'; return u.toString(); })();
const AMS = 'https://ams.example.org';
let pool: pg.Pool;

const request = (over: Partial<CollectRequest> = {}): CollectRequest => ({
  runId: 'run-1',
  evidence: { id: 'ev-1', title: 'Enrollment headcount', type: 'dataset', definition: null, columns: [{ key: 'n', label: 'N', type: 'integer', required: true }] },
  period: { label: 'Fall 2026', start: '2026-08-24', end: null },
  query: { metric: 'enrollment_headcount' },
  callbackUrl: `${AMS}/api/bi/v0/runs/run-1/supply`,
  callbackToken: 'tok-1',
  ...over,
});
const headcount: Source = {
  name: 'test', canAnswer: (r) => r.query?.metric === 'enrollment_headcount',
  answer: async (): Promise<SupplyBody> => ({ rows: [{ n: 120 }], asOf: '2026-10-20', lineage: { source: 'test' } }),
};

beforeAll(async () => {
  const admin = new pg.Client({ connectionString: ADMIN });
  await admin.connect();
  await admin.query('drop database if exists bi_test');
  await admin.query('drop role if exists bi_test');
  await admin.end();
  await ensureDatabase(ADMIN, DB_URL);
  await ensureDatabase(ADMIN, DB_URL); // twice: nothing to do the second time
  pool = new pg.Pool({ connectionString: DB_URL });
  expect(await migrate(pool)).toEqual(['0001_collect_request.sql']);
  expect(await migrate(pool)).toEqual([]);
});
afterAll(async () => { await pool?.end(); });
beforeEach(async () => { await pool.query('delete from collect_request'); });

describe('the AMS key', () => {
  it('matches only the exact bearer key', () => {
    expect(keyMatches('Bearer secret-key-0123456789', 'secret-key-0123456789')).toBe(true);
    expect(keyMatches('Bearer wrong', 'secret-key-0123456789')).toBe(false);
    expect(keyMatches(undefined, 'secret-key-0123456789')).toBe(false);
    expect(keyMatches('secret-key-0123456789', 'secret-key-0123456789')).toBe(false);
  });
});

describe('accepting a request', () => {
  it('keeps a request once per attempt, and a retry with a new token as a new one', async () => {
    const a = await acceptCollect(pool, request(), AMS);
    const again = await acceptCollect(pool, request(), AMS);
    const retry = await acceptCollect(pool, request({ callbackToken: 'tok-2' }), AMS);
    expect(a).toMatchObject({ ok: true, repeat: false });
    expect(again).toMatchObject({ ok: true, repeat: true, id: (a as { id: string }).id });
    expect(retry).toMatchObject({ ok: true, repeat: false });
    const stored = await pool.query('select request from collect_request limit 1');
    expect(stored.rows[0].request.callbackToken).toBeUndefined();
  });

  it('refuses a callback anywhere but the run\'s own supply route on the AMS', async () => {
    for (const callbackUrl of ['https://evil.example.org/api/bi/v0/runs/run-1/supply', `${AMS}/api/bi/v0/runs/run-2/supply`, `${AMS}/somewhere`]) {
      expect(await acceptCollect(pool, request({ callbackUrl }), AMS)).toMatchObject({ ok: false, status: 422, issues: [{ path: 'callbackUrl' }] });
    }
    expect(await acceptCollect(pool, { runId: 'x' }, AMS)).toMatchObject({ ok: false, status: 422 });
  });
});

describe('working a request', () => {
  const calls: { url: string; auth: string | null; body: unknown }[] = [];
  const answering = (status: number, json: unknown = {}): typeof fetch => (async (url: string, init: RequestInit) => {
    calls.push({ url, auth: new Headers(init.headers).get('authorization'), body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify(json), { status });
  }) as unknown as typeof fetch;
  beforeEach(() => { calls.length = 0; });

  it('answers from a source and calls the AMS back with the one-time token, then forgets the token', async () => {
    const { id } = await acceptCollect(pool, request(), AMS) as { id: string };
    const out = await processCollect({ pool, sources: new SourceRegistry([headcount]), callbackTimeoutMs: 1000, fetcher: answering(200) }, id);
    expect(out).toBe('supplied');
    expect(calls).toEqual([{ url: `${AMS}/api/bi/v0/runs/run-1/supply`, auth: 'Bearer tok-1', body: { rows: [{ n: 120 }], asOf: '2026-10-20', lineage: { source: 'test' } } }]);
    const row = (await pool.query('select status, callback_token, finished_at from collect_request where id = $1', [id])).rows[0];
    expect(row).toMatchObject({ status: 'supplied', callback_token: null });
    expect(await processCollect({ pool, sources: new SourceRegistry([headcount]), callbackTimeoutMs: 1000, fetcher: answering(200) }, id)).toBe('skipped');
  });

  it('never calls back without a source: no data means no supply', async () => {
    const { id } = await acceptCollect(pool, request({ query: { metric: 'graduation_rate' } }), AMS) as { id: string };
    expect(await processCollect({ pool, sources: new SourceRegistry([headcount]), callbackTimeoutMs: 1000, fetcher: answering(200) }, id)).toBe('no_source');
    expect(calls).toHaveLength(0);
  });

  it('ends on 401/409 and 422, and leaves a network error to the queue to retry', async () => {
    const deps = (f: typeof fetch) => ({ pool, sources: new SourceRegistry([headcount]), callbackTimeoutMs: 1000, fetcher: f });
    const a = await acceptCollect(pool, request({ callbackToken: 'a' }), AMS) as { id: string };
    expect(await processCollect(deps(answering(409)), a.id)).toBe('refused');
    const b = await acceptCollect(pool, request({ callbackToken: 'b' }), AMS) as { id: string };
    expect(await processCollect(deps(answering(422, { issues: [{ path: 'rows.0.n', message: 'enter a whole number' }] })), b.id)).toBe('failed');
    expect((await pool.query('select last_error from collect_request where id = $1', [b.id])).rows[0].last_error).toContain('rows.0.n');
    const c = await acceptCollect(pool, request({ callbackToken: 'c' }), AMS) as { id: string };
    const down = (async () => { throw new Error('connect ECONNREFUSED'); }) as unknown as typeof fetch;
    await expect(processCollect(deps(down), c.id)).rejects.toThrow(/ECONNREFUSED/);
    expect((await pool.query('select status, callback_token from collect_request where id = $1', [c.id])).rows[0]).toMatchObject({ status: 'running', callback_token: 'c' });
  });
});
