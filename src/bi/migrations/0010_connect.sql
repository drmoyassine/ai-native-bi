-- Connect data (docs/connect-data-spec.md, DEC-027 to DEC-031): sources, their streams, the layouts their data comes in, how a layout
-- maps to a dataset, and every sync. Replaces upload and column_mapping (0004, 0009).

create table source (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  slug text not null unique check (slug ~ '^[a-z][a-z0-9_]{0,40}$'),
  type text not null check (type in ('file')),
  settings jsonb not null default '{}',
  owner uuid references app_user (id),
  state text not null default 'draft' check (state in ('draft', 'live', 'paused')),
  created_at timestamptz not null default now(),
  approved_by uuid references app_user (id),
  approved_at timestamptz
);

-- One thing a source contains: a table, a sheet, the files of a file source. Its rows land in raw.<raw_table>.
create table source_stream (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references source (id) on delete cascade,
  name text not null,
  raw_table text not null unique,
  dataset text,
  created_at timestamptz not null default now(),
  unique (source_id, name)
);

-- The columns a stream's data comes in, as normalised in raw (name) and as written (header); id is a fingerprint of the names.
create table layout (
  id text primary key,
  columns jsonb not null,
  first_seen timestamptz not null default now()
);

-- Which column of a layout supplies which part of a dataset; the transforms read the approved ones.
create table layout_mapping (
  layout_id text not null references layout (id),
  dataset text not null,
  mapping jsonb not null,
  status text not null check (status in ('proposed', 'approved')),
  approved_by uuid references app_user (id),
  approved_how text,
  updated_at timestamptz not null default now(),
  primary key (layout_id, dataset)
);

-- One run of reading a stream. A file upload is a sync of a file source. `stale`: loaded before Connect data, to be loaded again.
create table sync (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references source (id) on delete cascade,
  stream_id uuid not null references source_stream (id) on delete cascade,
  user_id uuid references app_user (id),
  as_of date not null,
  sheet text,
  header_row integer,
  file_name text,
  incoming_url text,
  status text not null default 'queued' check (status in ('queued', 'running', 'review', 'loaded', 'failed', 'stale')),
  sha256 text,
  layout_id text references layout (id),
  found_header_row integer,
  notes jsonb,
  profile jsonb,
  rows integer,
  repeat boolean,
  tests integer,
  note text,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create index sync_source on sync (source_id, created_at desc);

-- Uploads become syncs of one file source per dataset; their rows were loaded under the old naming, so they are to be loaded again.
insert into source (name, slug, type, state, created_at)
select distinct initcap(dataset) || ' files', dataset || '_files', 'file', 'live', now() from upload;
insert into source_stream (source_id, name, raw_table, dataset)
select id, 'files', slug, substring(slug from '^(.*)_files$') from source;
insert into sync (source_id, stream_id, user_id, as_of, sheet, file_name, incoming_url, status, sha256, rows, repeat, tests, note, error,
                  created_at, finished_at)
select s.id, st.id, u.user_id, u.as_of, u.sheet, u.file_name, u.incoming_url,
       case u.status when 'loaded' then 'stale' else 'failed' end,
       u.sha256, u.rows, u.repeat, u.tests,
       case u.status when 'loaded' then 'Loaded before Connect data: load it again to bring it into this source.' end,
       case when u.status <> 'loaded' then coalesce(u.error, 'not finished before Connect data') end,
       u.created_at, u.finished_at
from upload u join source s on s.slug = u.dataset || '_files' join source_stream st on st.source_id = s.id;

drop table upload;
drop table column_mapping;
