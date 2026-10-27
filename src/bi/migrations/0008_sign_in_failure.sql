-- Failed sign-ins (TASK-010): by the email typed (whether or not it exists, so a refusal reveals nothing) and by client address.
-- Too many in the window refuses further attempts; a successful sign-in clears that email's rows; old rows are pruned as new ones arrive.
create table sign_in_failure (
  id bigserial primary key,
  at timestamptz not null default now(),
  email text not null,
  ip text not null
);
create index sign_in_failure_email on sign_in_failure (email, at);
create index sign_in_failure_ip on sign_in_failure (ip, at);
