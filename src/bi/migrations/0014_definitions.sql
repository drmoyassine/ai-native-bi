-- What the organization reports on, as definitions (docs/data-model-spec.md, M1; DEC-036): subjects, entities and events, each a
-- versioned JSON body checked by bi.definitions. A change is a draft until a person approves it; the current definition is the latest
-- approved version. Definitions a template made carry its name.
create table definition (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('subject', 'entity', 'event')),
  name text not null check (name ~ '^[a-z][a-z0-9_]{0,62}$'),
  version integer not null check (version > 0),
  status text not null check (status in ('draft', 'approved', 'retired')),
  body jsonb not null,
  template text,
  created_by uuid references app_user (id),
  created_at timestamptz not null default now(),
  approved_by uuid references app_user (id),
  approved_at timestamptz,
  unique (kind, name, version)
);
create unique index definition_one_draft on definition (kind, name) where status = 'draft';

-- The Cube model the BI writes (M0b): files Cube reads through cube/cube.js, besides any in cube/model. Cube's role may read this
-- schema and analytics, nothing else (granted by bi.db.grant_analytics).
create schema if not exists cube_model;
create table cube_model.file (
  name text primary key check (name ~ '^[a-z0-9_./-]+\.yml$'),
  content text not null,
  source text not null,
  updated_at timestamptz not null default now()
);
