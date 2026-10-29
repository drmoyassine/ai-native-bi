-- The organization's calendars (docs/data-model-spec.md section 4; TASK-043): its own periods (terms, fiscal years, seasons, shifts),
-- either listed with their dates or repeating every year from a start day, each a JSON body checked by bi.calendars. An event's derived
-- part says which period of a calendar a date falls in. Calendar years and months need no calendar (a part of a date).
create table calendar (
  name text primary key check (name ~ '^[a-z][a-z0-9_]{0,62}$'),
  body jsonb not null,
  updated_by uuid references app_user (id),
  updated_at timestamptz not null default now()
);
