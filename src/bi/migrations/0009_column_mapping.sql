-- Which column of a dataset's files plays which part (ROADMAP-009): discovered from the file's own headers, approved by a person when
-- the match is not exact. The transform reads the approved mapping; raw keeps the file's columns as they are.
create table column_mapping (
  dataset text primary key,
  mapping jsonb not null,
  status text not null check (status in ('proposed', 'approved')),
  approved_by uuid references app_user (id),
  approved_how text,
  error text,
  built_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table upload add column note text;
