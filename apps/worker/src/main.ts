import { PgBoss } from 'pg-boss';
import pg from 'pg';
import { COLLECT_QUEUE, loadEnv, processCollect, SourceRegistry } from '@bi/core';

const env = loadEnv();
const pool = new pg.Pool({ connectionString: env.DATABASE_URL });
const boss = new PgBoss(env.DATABASE_URL);
boss.on('error', (err) => console.error(JSON.stringify({ level: 'error', msg: 'pg-boss', err: String(err) })));
await boss.start();
await boss.createQueue(COLLECT_QUEUE);

// No sources yet: every request ends as no_source until the metric layer registers some (packages/core/src/sources.ts).
const sources = new SourceRegistry([]);
await boss.work<{ id: string }>(COLLECT_QUEUE, { pollingIntervalSeconds: 2 }, async (jobs) => {
  for (const job of jobs) {
    const outcome = await processCollect({ pool, sources, callbackTimeoutMs: env.CALLBACK_TIMEOUT_MS }, job.data.id);
    console.log(JSON.stringify({ level: 'info', msg: 'collect', id: job.data.id, outcome }));
  }
});
console.log(JSON.stringify({ level: 'info', msg: 'bi worker started', queues: [COLLECT_QUEUE] }));
