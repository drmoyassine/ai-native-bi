-- Column decisions at review (Connect data C1b, docs/connect-data-spec.md § 6.7): what a person decided about each column of a stream,
-- kept by column name so a later layout keeps them. Unset means "as detected".
create table stream_column (
  stream_id uuid not null references source_stream (id) on delete cascade,
  name text not null,
  personal text check (personal in ('identifying', 'describing', 'none')),
  reason text,
  keep boolean not null default true,
  kind text check (kind in ('text', 'number', 'date', 'category', 'identifier', 'boolean')),
  label jsonb not null default '{}',
  description jsonb not null default '{}',
  decided_by uuid references app_user (id),
  decided_at timestamptz not null default now(),
  primary key (stream_id, name)
);
-- The columns that identify a row of the stream (checked before approval).
alter table source_stream add column row_key text[];
