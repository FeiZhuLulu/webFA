# Storage migrations

The current Runtime upgrades SQLite additively through SQLAlchemy metadata and records applied schema milestones in `storage_migrations`.

P12.1 introduces migration id:

```text
p12_001_profile_catalog
```

It creates the Profile and Session catalog tables without reading or copying browser secrets:

- `browser_profiles`
- `browser_profile_agent_bindings`
- `browser_sessions`
- `browser_profile_runtime_events`
- `storage_migrations`

Existing databases are upgraded by `storage.db.init_db()` using `create_all(checkfirst)` semantics, then the migration id is recorded. Destructive or column-rewrite migrations must use a formal Alembic revision before they are added; they must not be hidden inside application startup code.
