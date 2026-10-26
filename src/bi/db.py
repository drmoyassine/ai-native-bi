from __future__ import annotations

from importlib import resources
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

MIGRATION_LOCK = 7313001


async def ensure_database(admin_url: str, database_url: str) -> None:
    """Co-deployment (AMS DEC-034): on the AMS's PostgreSQL server, create the BI's own role and database from DATABASE_URL when they
    are missing. The BI never reads the AMS's database; the admin address is used for this and nothing else."""
    target = urlsplit(database_url)
    user = unquote(target.username or '')
    password = unquote(target.password or '')
    db = target.path.lstrip('/')
    if not user or not db:
        raise ValueError('DATABASE_URL must name a user and a database')
    async with await psycopg.AsyncConnection.connect(admin_url, autocommit=True) as admin:
        if not await (await admin.execute('select 1 from pg_roles where rolname = %s', [user])).fetchone():
            await admin.execute(sql.SQL('create role {} login password {}').format(sql.Identifier(user), sql.Literal(password)))
        if not await (await admin.execute('select 1 from pg_database where datname = %s', [db])).fetchone():
            await admin.execute(sql.SQL('create database {} owner {}').format(sql.Identifier(db), sql.Identifier(user)))


def migration_names() -> list[str]:
    folder = resources.files('bi') / 'migrations'
    return sorted(f.name for f in folder.iterdir() if f.name.endswith('.sql'))


async def migrate(pool: AsyncConnectionPool) -> list[str]:
    """Applies the forward-only SQL migrations in src/bi/migrations, in name order, once each."""
    folder = resources.files('bi') / 'migrations'
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        await conn.execute('select pg_advisory_lock(%s)', [MIGRATION_LOCK])
        try:
            await conn.execute(
                'create table if not exists schema_migration (name text primary key, applied_at timestamptz not null default now())'
            )
            done = {r[0] for r in await (await conn.execute('select name from schema_migration')).fetchall()}
            applied: list[str] = []
            for name in migration_names():
                if name in done:
                    continue
                async with conn.transaction():
                    # A migration file is trusted SQL from this repository, never input.
                    await conn.execute((folder / name).read_text('utf-8'))
                    await conn.execute('insert into schema_migration (name) values (%s)', [name])
                applied.append(name)
            return applied
        finally:
            await conn.execute('select pg_advisory_unlock(%s)', [MIGRATION_LOCK])
