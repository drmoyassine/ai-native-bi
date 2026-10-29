-- The templates an organization installed (DEC-037): what its sources can feed comes from them, never from code. At start the API
-- installs any template whose datasets streams already feed (organization.install_fed_templates), so an existing installation keeps
-- working without this migration naming one.
alter table organization add column installed_templates text[] not null default '{}';
