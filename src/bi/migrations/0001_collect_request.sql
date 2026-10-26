-- One request of the AMS for one collection run and attempt (contract 3.6). The AMS makes a new token for each attempt, so a
-- retry of the same run is a new row; a repeat of the same attempt (same run and token) is the same row.
create table collect_request (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  token_hash text not null,
  -- Needed to call back; cleared the moment the request ends (supplied, refused or given up), like the AMS clears its hash.
  callback_token text,
  callback_url text not null,
  request jsonb not null,
  status text not null default 'queued' check (status in ('queued', 'running', 'supplied', 'no_source', 'refused', 'failed')),
  attempts integer not null default 0,
  last_error text,
  received_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (run_id, token_hash)
);
create index collect_request_status on collect_request (status);
