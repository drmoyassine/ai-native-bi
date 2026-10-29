-- The organization's own settings (DEC-037, DEC-038): its name in the primary language and in its secondary one, the one secondary
-- language (a code of bi.languages), the interface language for people who have not chosen one, and an accent colour. One row.
create table organization (
  id boolean primary key default true check (id),
  name text not null default '',
  name_secondary text,
  secondary_language text,
  default_locale text not null default 'en',
  accent_color text,
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user (id)
);
insert into organization default values;

-- Each person's interface language: the primary language or the organization's secondary one; null follows the default.
alter table app_user add column language text;
