# ATLAS persistence migrations

Migrations run in filename order and are recorded in `schema_migrations`. New
schema changes must be additive and use a new numbered SQL file. Existing
migration files must not be edited after release.
