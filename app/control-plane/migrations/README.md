
## Database Migration
- Done via `alembic`.
- Initialization command : `alembic init migrations`
- Create a database migration : `alembic revision --autogenerate -m "<migration-description>"`
- Apply migration current state to database : `alembic upgrade head`
- See migration history : `alembic upgrade head`
- See latest migration :  `alembic heads`
- Upgrade by n migrations from the stack : `alembic upgrade +1` or `alembic upgrade +2` ....
- Upgrade to specific migration : `alembic upgrade <migration-hash>`
- Rollback by n migration from the stack : `alembic downgrade -1` or `alembic downgrade -2` ....
- Rollback to specific migration : `alembic downgrade <migration-hash>`
- Create an empty migration : `alembic revision -m "migrate cluster endpoints"`
- Review SQL before applying migration : `alembic upgrade head --sql`
- Generate SQL for a range of migration : `alembic upgrade base:head --sql`
