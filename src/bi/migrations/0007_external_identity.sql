-- People signed in by another issuer (the AMS, contract 6.2; docs/mcp-spec.md step 3c). They have no password here: the issuer's token
-- says who they are and, at every call, their role and scope. Their local record only owns their drafts and access log entries.
alter table app_user alter column password_hash drop not null;

create table external_identity (
  issuer text not null,
  subject text not null,
  user_id uuid not null references app_user (id),
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  primary key (issuer, subject)
);
create index external_identity_user on external_identity (user_id);
