-- The app (ROADMAP-009): the BI's own accounts, their sessions, and files uploaded through it.

create table app_user (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  name text not null,
  -- Argon2id (argon2-cffi); never the password itself.
  password_hash text not null,
  is_admin boolean not null default false,
  created_at timestamptz not null default now(),
  disabled_at timestamptz
);
create unique index app_user_email on app_user (lower(email));

-- A signed-in browser. The cookie holds a random token; only its SHA-256 is kept here.
create table app_session (
  id uuid primary key default gen_random_uuid(),
  token_hash text not null unique,
  user_id uuid not null references app_user (id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index app_session_user on app_session (user_id);

-- A file uploaded through the app: kept under incoming/ until the worker loads it (bi.ingest) and rebuilds analytics (dbt).
create table upload (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user (id),
  dataset text not null,
  as_of date not null,
  sheet text,
  file_name text not null,
  incoming_url text not null,
  status text not null default 'queued' check (status in ('queued', 'running', 'loaded', 'failed')),
  sha256 text,
  rows integer,
  repeat boolean,
  tests integer,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create index upload_created on upload (created_at desc);
