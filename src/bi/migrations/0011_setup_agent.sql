-- The setup agent (docs/setup-agent-spec.md, DEC-032, DEC-035): masked sample rows only to providers an admin allowed, every sample
-- logged, the agent's mapping proposals kept with their reasons, and its token use counted against the budgets.

alter table model_provider add column may_see_samples boolean not null default false;

create table sample_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  user_id uuid references app_user (id),
  sync_id uuid references sync (id) on delete set null,
  provider_id uuid references model_provider (id) on delete set null,
  model_id text,
  purpose text not null,
  rows integer not null,
  masked jsonb not null default '{}'
);
create index sample_log_at on sample_log (at desc);

-- Who proposed a layout's mapping, and why: the rules, the setup agent or a person.
alter table layout_mapping
  add column proposed_by text not null default 'rules' check (proposed_by in ('rules', 'agent', 'person')),
  add column reasons jsonb,
  add column model text;

-- The agent's part of a sync: its state (queued, running, proposed, failed, none), the header row it suggests, notes on columns.
alter table sync add column agent jsonb;

-- One setup call of the agent: what it cost, for the institution's and the person's monthly budgets (DEC-020).
create table setup_run (
  id bigserial primary key,
  sync_id uuid references sync (id) on delete set null,
  provider_id uuid references model_provider (id) on delete set null,
  model_id text,
  input_tokens bigint not null default 0,
  output_tokens bigint not null default 0,
  requests integer not null default 0,
  status text not null check (status in ('done', 'failed')),
  error text,
  created_at timestamptz not null default now()
);
create index setup_run_created on setup_run (created_at);
