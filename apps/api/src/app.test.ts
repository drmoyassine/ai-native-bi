import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { ensureDatabase, migrate } from '@bi/core';
import { createApp } from './app.js';

const ADMIN = process.env.TEST_DATABASE_ADMIN_URL!;
const DB_URL = (() => { const u = new URL(ADMIN); u.username = 'bi_api_test'; u.password = 'bi_api_test_pw'; u.pathname = '/bi_api_test'; return u.toString(); })();
const KEY = 'test-key-0123456789';
const AMS = 'https://ams.example.org';
let pool: pg.Pool;
const queued: string[] = [];

const body = (runId = 'run-1', token = 'tok-1') => ({
  runId, evidence: { id: 'ev-1', title: 'Headcount', type: 'dataset', definition: null },
  period: { label: 'Fall 2026', start: '2026-08-24', end: null }, query: null,
  callbackUrl: `${AMS}/api/bi/v0/runs/${runId}/supply`, callbackToken: token,
});

beforeAll(async () => {
  const admin = new pg.Client({ connectionString: ADMIN });
  await admin.connect();
  await admin.query('drop database if exists bi_api_test');
  await admin.query('drop role if exists bi_api_test');
  await admin.end();
  await ensureDatabase(ADMIN, DB_URL);
  pool = new pg.Pool({ connectionString: DB_URL });
  await migrate(pool);
});
afterAll(async () => { await pool?.end(); });

describe('POST /ams/collect', () => {
  const app = () => createApp({ pool, apiKey: KEY, amsOrigin: AMS, enqueue: async (id) => { queued.push(id); } });
  const post = (path: string, b: unknown, key: string | null = KEY) => app().request(path, {
    method: 'POST', body: JSON.stringify(b), headers: { 'content-type': 'application/json', ...(key ? { authorization: `Bearer ${key}` } : {}) },
  });

  it('answers 202 and queues the work once per attempt, on the default path and a named one', async () => {
    expect((await post('/ams/collect', body())).status).toBe(202);
    expect((await post('/ams/collect', body())).status).toBe(202);
    expect((await post('/ams/collect/warehouse', body('run-2'))).status).toBe(202);
    expect(queued).toHaveLength(2);
  });

  it('refuses a wrong key (401), a body that does not fit (422) and a foreign callback (422)', async () => {
    expect((await post('/ams/collect', body(), 'wrong')).status).toBe(401);
    expect((await post('/ams/collect', body(), null)).status).toBe(401);
    expect((await post('/ams/collect', { runId: 'x' })).status).toBe(422);
    const foreign = await post('/ams/collect', { ...body(), callbackUrl: 'https://evil.example.org/api/bi/v0/runs/run-1/supply' });
    expect(foreign.status).toBe(422);
    expect(await foreign.json()).toMatchObject({ issues: [{ path: 'callbackUrl' }] });
  });

  it('is healthy', async () => {
    expect((await app().request('/healthz')).status).toBe(200);
  });
});
