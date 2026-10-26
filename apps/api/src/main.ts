import { serve } from '@hono/node-server';
import { PgBoss } from 'pg-boss';
import pg from 'pg';
import { COLLECT_QUEUE, ensureDatabase, loadEnv, migrate } from '@bi/core';
import { createApp } from './app.js';

const env = loadEnv();
if (env.BI_DATABASE_ADMIN_URL) await ensureDatabase(env.BI_DATABASE_ADMIN_URL, env.DATABASE_URL);
const pool = new pg.Pool({ connectionString: env.DATABASE_URL });
const applied = await migrate(pool);
if (applied.length) console.log(JSON.stringify({ level: 'info', msg: 'migrated', applied }));

const boss = new PgBoss(env.DATABASE_URL);
boss.on('error', (err) => console.error(JSON.stringify({ level: 'error', msg: 'pg-boss', err: String(err) })));
await boss.start();
await boss.createQueue(COLLECT_QUEUE);

const app = createApp({
  pool, apiKey: env.BI_API_KEY, amsOrigin: env.AMS_CALLBACK_ORIGIN,
  enqueue: async (id) => { await boss.send(COLLECT_QUEUE, { id }, { retryLimit: 5, retryDelay: 60, retryBackoff: true }); },
});
serve({ fetch: app.fetch, port: env.PORT }, (info) => console.log(JSON.stringify({ level: 'info', msg: 'bi api listening', port: info.port })));
