-- The agent (ROADMAP-003, docs/agent-spec.md step 2a): secrets, model providers and their models, conversations, runs, events, drafts.

-- Secrets: a value is stored only encrypted (AES-GCM, BI_SECRETS_KEY); the agent and the model see only the handle.
create table secret (
  handle text primary key,
  nonce bytea not null,
  ciphertext bytea not null,
  created_by uuid references app_user (id),
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

-- The five kinds of model provider (DEC-016), configured by an admin. The key is a handle into `secret`.
create table model_provider (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('anthropic', 'openai', 'openai_compatible', 'openrouter', 'ollama')),
  name text not null,
  base_url text,
  key_handle text,
  enabled boolean not null default true,
  fetched_at timestamptz,
  fetch_error text,
  created_at timestamptz not null default now()
);
create unique index model_provider_name on model_provider (lower(name));

-- The models a provider lists, fetched automatically; an admin allows them per mode and sets a default for each.
create table provider_model (
  provider_id uuid not null references model_provider (id) on delete cascade,
  model_id text not null,
  name text,
  context_window integer,
  output_limit integer,
  price_in numeric,   -- USD per million tokens, where the provider says
  price_out numeric,
  tool_support text not null default 'unknown' check (tool_support in ('yes', 'no', 'unknown')),
  tool_support_via text check (tool_support_via in ('list', 'test')),
  available boolean not null default true,
  allowed_ask boolean not null default false,
  allowed_build boolean not null default false,
  default_ask boolean not null default false,
  default_build boolean not null default false,
  fetched_at timestamptz,
  primary key (provider_id, model_id)
);
-- At most one default model per mode.
create unique index provider_model_default_ask on provider_model (default_ask) where default_ask;
create unique index provider_model_default_build on provider_model (default_build) where default_build;

create table conversation (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references app_user (id),
  mode text not null check (mode in ('ask', 'build')),
  title text not null default 'New conversation',
  provider_id uuid not null references model_provider (id),
  model_id text not null,
  created_at timestamptz not null default now(),
  archived_at timestamptz
);
create index conversation_owner on conversation (owner_id, created_at desc);

-- Pydantic AI messages exactly as sent and received (DEC-018): appended, never edited or deleted.
create table conversation_message (
  conversation_id uuid not null references conversation (id) on delete cascade,
  seq integer not null,
  kind text not null check (kind in ('request', 'response')),
  message jsonb not null,
  created_at timestamptz not null default now(),
  primary key (conversation_id, seq)
);

-- One run per user message (a turn).
create table agent_run (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversation (id) on delete cascade,
  status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed', 'interrupted')),
  interrupt_requested boolean not null default false,
  stop_reason text,
  requests integer not null default 0,
  input_tokens bigint not null default 0,
  output_tokens bigint not null default 0,
  cache_read_tokens bigint not null default 0,
  cache_write_tokens bigint not null default 0,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index agent_run_conversation on agent_run (conversation_id, created_at desc);
create index agent_run_month on agent_run (created_at);

-- What the chat streams (docs/agent-spec.md section 9); kept 30 days.
create table agent_event (
  id bigserial primary key,
  conversation_id uuid not null references conversation (id) on delete cascade,
  run_id uuid references agent_run (id) on delete cascade,
  type text not null,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index agent_event_conversation on agent_event (conversation_id, id);

-- What a person or the agent builds: private until approved to publish (DEC-013).
create table draft (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('chart')),
  owner_id uuid not null references app_user (id),
  built_by text not null check (built_by in ('person', 'agent')),
  conversation_id uuid references conversation (id) on delete set null,
  definition jsonb not null,
  state text not null default 'draft' check (state in ('draft', 'published')),
  created_at timestamptz not null default now()
);
create index draft_owner on draft (owner_id, created_at desc);
