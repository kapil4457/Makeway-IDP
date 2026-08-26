# Makeway Control-Plane Scripts

Operational CLI tools for bootstrapping and managing Makeway users, teams and
team memberships. Every script is a thin argument-parsing wrapper; all business
logic lives in [`scripts/lib/`](lib/) so the scripts never duplicate each other.

## Prerequisites

- The control-plane virtualenv is active:
  ```bash
  cd app/control-plane
  . .venv/Scripts/activate        # Windows
  ```
- The database is reachable (see `DATABASE_URL` in `.env`).
- Logging: every script writes JSON-lines to stdout and `logs/makeway.jsonl`.
  Configure via `LOG_LEVEL`, `MAKEWAY_LOG_DIR`, `MAKEWAY_LOG_MAX_BYTES`,
  `MAKEWAY_LOG_BACKUPS`.

## Default password

Users created by these scripts get `FORGE_DEFAULT_PASSWORD` as their password
when none is supplied on the command line (default: `changeme123`). Set the env
var to override — e.g. `FORGE_DEFAULT_PASSWORD='…'`. Production usage should
always pass an explicit `--password`.

## Common flags

- `--dry-run` — validate arguments and show intent without touching the database.
- `--help` — full usage for a script.

---

## `create_user.py`

Create a user (idempotent — existing users are left untouched).

```bash
python -m scripts.create_user --email "dev@example.com" --password "s3cret"
python -m scripts.create_user --email "dev@example.com"           # uses FORGE_DEFAULT_PASSWORD
python -m scripts.create_user --email "dev@example.com" --dry-run
```

| Flag | Required | Description |
|---|---|---|
| `--email` | yes | Email (unique identifier) of the user |
| `--password` | no | Password; defaults to `FORGE_DEFAULT_PASSWORD` |
| `--dry-run` | no | Validate and exit without creating |

---

## `create_team.py`

Create a team with an owner and optional members. The owner is added with
role `owner`; additional members get role `member`. Users are created if they
don't exist (idempotent).

```bash
# Team with owner only
python -m scripts.create_team --team-name "platform" --owner-email "admin@example.com"

# Team with owner + members (single shared password)
python -m scripts.create_team --team-name "platform" \
    --owner-email "admin@example.com" \
    --members "alice@example.com,bob@example.com"

# Distinct passwords for owner vs members
python -m scripts.create_team --team-name "platform" \
    --owner-email "admin@example.com" --owner-password "admin-pw" \
    --members "alice@example.com,bob@example.com" --member-password "member-pw"

# Preview without writing
python -m scripts.create_team --team-name "platform" \
    --owner-email "admin@example.com" --dry-run
```

| Flag | Required | Description |
|---|---|---|
| `--team-name` | yes | Name of the team to create |
| `--owner-email` | yes | Owner email; user is created if missing |
| `--owner-password` | no | Owner password; defaults to `FORGE_DEFAULT_PASSWORD` |
| `--members` | no | Comma-separated member emails to add as `member` |
| `--member-password` | no | Member password; defaults to `FORGE_DEFAULT_PASSWORD` |
| `--dry-run` | no | Validate and exit without creating |

---

## `list_teams.py`

List all teams, their creation info and active members.

```bash
python -m scripts.list_teams
```

Takes no arguments. Soft-deleted memberships (`isDeleted = true`) are excluded.

---

## `manage_team_members.py`

Add, remove or change the role of members on an **existing** team.
At least one of `--add`, `--remove` or `--update-role` is required.

```bash
# Add members (users auto-created if missing)
python -m scripts.manage_team_members --team-name "platform" \
    --add "carol@example.com,dave@example.com" --actor-email "admin@example.com"

# Remove members (soft delete — isDeleted=true)
python -m scripts.manage_team_members --team-name "platform" \
    --remove "alice@example.com" --actor-email "admin@example.com"

# Promote a member (or demote / assign admin)
python -m scripts.manage_team_members --team-name "platform" \
    --update-role "alice@example.com" --role owner --actor-email "admin@example.com"

# Combine actions in one run
python -m scripts.manage_team_members --team-name "platform" \
    --add "carol@example.com" --remove "bob@example.com" \
    --update-role "alice@example.com" --role owner \
    --actor-email "admin@example.com"

# Preview without writing
python -m scripts.manage_team_members --team-name "platform" \
    --add "carol@example.com" --actor-email "admin@example.com" --dry-run
```

| Flag | Required | Description |
|---|---|---|
| `--team-name` | yes | Name of the **existing** team |
| `--actor-email` | yes | Email of the person running the action (audit trail) |
| `--add` | no | Comma-separated emails to add as members |
| `--remove` | no | Comma-separated emails to soft-delete from the team |
| `--update-role` | no | Single email whose role should change |
| `--role` | no | Role for add/update: `member`, `owner` or `admin` (default `member`) |
| `--password` | no | Password for users auto-created via `--add`; defaults to `FORGE_DEFAULT_PASSWORD` |
| `--dry-run` | no | Validate and exit without writing |

---

## Shared library (`scripts/lib/`)

| Module | Purpose |
|---|---|
| [`lib/operations.py`](lib/operations.py) | All user/team/membership DB logic: `get_user`, `get_or_create_user`, `get_team`, `get_or_create_team`, `list_teams_with_members`, `upsert_team_member`, `remove_team_member`, `update_team_member_role` |
| [`lib/cli.py`](lib/cli.py) | Shared `argparse` helpers: `build_parser`, `parse_csv`, `add_dry_run_flag`, `log_dry_run` |
| [`lib/config.py`](lib/config.py) | `DEFAULT_PASSWORD` from `FORGE_DEFAULT_PASSWORD` |
| [`lib/__init__.py`](lib/__init__.py) | Bootstraps structured logging once |

Importing anything from `scripts.lib` initializes JSON logging. Scripts should
stay CLI-only and delegate all business logic to `lib/operations.py`.

## Membership semantics (idempotent)

- Adding a user who is **not** a member → membership created.
- Adding a **soft-deleted** member → membership restored with the new role.
- Adding an active member with a **different** role → role updated.
- Adding an active member with the **same** role → no-op.
- Removing a member who is already removed / doesn't exist → no-op.

All operations run in a single transaction and commit only on success.