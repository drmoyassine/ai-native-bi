-- A source that knows the metric but has no data for the period ends the request `no_data` (the AMS is not called: no data, no
-- supply). The check constraint is the inline one of 0001, named by PostgreSQL's default.
alter table collect_request drop constraint collect_request_status_check;
alter table collect_request add constraint collect_request_status_check
  check (status in ('queued', 'running', 'supplied', 'no_source', 'no_data', 'refused', 'failed'));
