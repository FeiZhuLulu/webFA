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

Existing databases are upgraded by `storage.db.init_db()` using
`create_all(checkfirst)` semantics. The migration milestone and required
Provider seed rows are committed in one transaction only after schema creation
succeeds. The full additive initialization sequence is serialized by an OS file
lock scoped to the shared WebFA data directory. This prevents concurrent
Runtime processes from racing on first startup or an existing-database upgrade,
and prevents a failed seed from leaving a falsely applied migration milestone.

Every Runtime SQLite connection explicitly enables foreign-key enforcement and
a bounded busy timeout. The Profile/Session foreign keys are therefore runtime
integrity constraints, not metadata-only declarations. Existing database rows
are preserved by this additive milestone; destructive or column-rewrite
migrations must use a formal Alembic revision before they are added and must not
be hidden inside application startup code.
