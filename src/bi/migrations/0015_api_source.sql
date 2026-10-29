-- REST API sources (Connect data C2, docs/connect-data-spec.md): one source per API, one stream per endpoint. Its settings (base URL,
-- endpoints, authentication kind, schedule) are in source.settings, checked by bi.connect.api; its credential is in the secret store.
alter table source drop constraint source_type_check;
alter table source add constraint source_type_check check (type in ('file', 'api'));
-- The file a sync of an API source read is no file: the endpoint it read stands in for it.
alter table sync add column endpoint text;
