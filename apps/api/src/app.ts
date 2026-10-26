import { Hono } from 'hono';
import type pg from 'pg';
import { acceptCollect, keyMatches } from '@bi/core';

export interface AppDeps {
  pool: pg.Pool;
  apiKey: string;
  amsOrigin: string;
  /** Queues the work of one accepted request (pg-boss in production). */
  enqueue: (id: string) => Promise<void>;
}

/**
 * The BI's HTTP surface. Today: the AMS's request for one collection run (contract 3.6). It is always answered asynchronously:
 * 202 at once, then the worker calls the AMS back (4.2). The default path is /ams/collect; the AMS's BI_ENDPOINTS may name more paths
 * under it (/ams/collect/<name>), which land here too and carry the name in the body's `endpoint`.
 */
export function createApp(deps: AppDeps): Hono {
  const app = new Hono();
  app.get('/healthz', (c) => c.json({ ok: true }));

  const collect = async (c: import('hono').Context) => {
    if (!keyMatches(c.req.header('authorization'), deps.apiKey)) return c.json({ error: 'unauthorized' }, 401);
    const body = await c.req.json().catch(() => undefined);
    if (body === undefined) return c.json({ error: 'bad_request', message: 'the body must be JSON' }, 400);
    const r = await acceptCollect(deps.pool, body, deps.amsOrigin);
    if (!r.ok) return c.json({ error: 'invalid', message: 'the request does not fit the contract', issues: r.issues }, r.status);
    if (!r.repeat) await deps.enqueue(r.id);
    return c.body(null, 202);
  };
  app.post('/ams/collect', collect);
  app.post('/ams/collect/:endpoint{[A-Za-z0-9_.-]+}', collect);
  return app;
}
