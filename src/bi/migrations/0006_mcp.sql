-- The MCP server (ROADMAP-004, docs/mcp-spec.md step 3a): personal access tokens and the access log.

-- A personal access token acts as its person. Only its SHA-256 hash is kept; the token is shown once, when it is made.
create table access_token (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user (id),
  name text not null check (length(name) between 1 and 80),
  token_hash text not null unique,
  hint text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_used_at timestamptz,
  revoked_at timestamptz
);
create index access_token_user on access_token (user_id, created_at desc);

-- Every call of an MCP tool: who, which tool, what was asked (a structured query, never a secret), what came back.
create table access_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  user_id uuid references app_user (id),
  issuer text not null,
  client_id text,
  tool text not null,
  arguments jsonb not null default '{}',
  rows integer,
  suppressed_cells integer,
  outcome text not null check (outcome in ('ok', 'error', 'limited')),
  error text
);
create index access_log_user_at on access_log (user_id, at desc);
