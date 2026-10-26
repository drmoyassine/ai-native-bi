import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import pg from 'pg';

const MIGRATIONS = fileURLToPath(new URL('../migrations/', import.meta.url));
const ident = (s: string) => `"${s.replace(/"/g, '""')}"`;
const literal = (s: string) => `'${s.replace(/'/g, "''")}'`;

/**
 * Co-deployment (AMS DEC-034): on the AMS's PostgreSQL server, create the BI's own role and database from DATABASE_URL when they
 * are missing. The BI never reads the AMS's database; the admin address is used for this and nothing else.
 */
export async function ensureDatabase(adminUrl: string, databaseUrl: string): Promise<void> {
  const target = new URL(databaseUrl);
  const user = decodeURIComponent(target.username);
  const password = decodeURIComponent(target.password);
  const db = target.pathname.replace(/^\//, '');
  if (!user || !db) throw new Error('DATABASE_URL must name a user and a database');
  const admin = new pg.Client({ connectionString: adminUrl });
  await admin.connect();
  try {
    const role = await admin.query('select 1 from pg_roles where rolname = $1', [user]);
    if (!role.rowCount) await admin.query(`create role ${ident(user)} login password ${literal(password)}`);
    const exists = await admin.query('select 1 from pg_database where datname = $1', [db]);
    if (!exists.rowCount) await admin.query(`create database ${ident(db)} owner ${ident(user)}`);
  } finally {
    await admin.end();
  }
}

/** Applies the forward-only SQL migrations in packages/core/migrations, in name order, once each. */
export async function migrate(pool: pg.Pool): Promise<string[]> {
  const client = await pool.connect();
  try {
    await client.query('select pg_advisory_lock(7313001)');
    await client.query('create table if not exists schema_migration (name text primary key, applied_at timestamptz not null default now())');
    const done = new Set((await client.query<{ name: string }>('select name from schema_migration')).rows.map((r) => r.name));
    const applied: string[] = [];
    for (const name of (await readdir(MIGRATIONS)).filter((f) => f.endsWith('.sql')).sort()) {
      if (done.has(name)) continue;
      const sql = await readFile(MIGRATIONS + name, 'utf8');
      await client.query('begin');
      try {
        await client.query(sql);
        await client.query('insert into schema_migration (name) values ($1)', [name]);
        await client.query('commit');
      } catch (e) {
        await client.query('rollback');
        throw e;
      }
      applied.push(name);
    }
    return applied;
  } finally {
    await client.query('select pg_advisory_unlock(7313001)').catch(() => {});
    client.release();
  }
}
