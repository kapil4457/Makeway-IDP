# Database Migrations

> [Documentation index](../../../docs/README.md) › Components › Control plane › Migrations

Schema migrations are managed with [Alembic](https://alembic.sqlalchemy.org/).
Migration scripts live in [`versions/`](versions/); the revision graph is a
single linear chain.

## How it is wired

- [`alembic.ini`](../alembic.ini) sets `script_location` to this folder and
  `prepend_sys_path = .` so imports resolve against `app/control-plane`.
- [`env.py`](env.py) imports `database.models` — the central model registry —
  and points autogenerate at `SQLModel.metadata`. New tables only need to be
  registered in `database/models/__init__.py`; adding them here too would
  duplicate the registry and silently drop them from autogenerate.
- The connection URL comes from the `DATABASE_URL` environment variable
  (`env.py`), falling back to
  `postgresql://postgres:password@127.0.0.1:5432/makeway?sslmode=require`.
  The `sqlalchemy.url` in `alembic.ini` is only a placeholder — `env.py`
  overrides it at runtime.

## Common commands

Run from `app/control-plane/` (where `alembic.ini` lives):

```bash
# Generate a migration from the current model state
alembic revision --autogenerate -m "<migration-description>"

# Generate an empty migration (hand-written operations)
alembic revision -m "<migration-description>"

# Apply all pending migrations
alembic upgrade head

# Upgrade / downgrade relatively
alembic upgrade +1
alembic downgrade -1

# Upgrade / rollback to a specific revision
alembic upgrade <revision>
alembic downgrade <revision>

# Review the SQL before applying (offline mode — no database needed)
alembic upgrade head --sql
alembic upgrade base:head --sql

# Show the revision graph and the current head(s)
alembic history
alembic heads

# Show the revision the database is currently at
alembic current
```

> **Autogenerate is a draft, not a diff to trust blindly.** Review the
> generated script before applying — Alembic cannot see data migrations,
> server defaults on existing rows, or Postgres enum value changes. Enums are
> `str`-based Python enums whose *member names* (e.g. `FAST_API`) are what
> SQLAlchemy persists into Postgres enum columns; migrations touching enum
> types must hard-code those member names.

## Migration scripts

Each revision in [`versions/`](versions/) exposes `upgrade()` and
`downgrade()`. Revisions are chained with `down_revision` — `alembic heads`
prints `head` when the chain has no forks. If `alembic heads` prints more
than one revision, a branch was created and must be merged with
`alembic merge` before `upgrade head` works again.
