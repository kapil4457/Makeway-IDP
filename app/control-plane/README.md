# Makeway Control Plane

> [Documentation index](../../docs/README.md) › Components › Control plane

The FastAPI service at the center of Makeway. It owns the PostgreSQL data
model, exposes the user-facing API (app onboarding, clusters, auth), and
serves the internal state-machine API the AWS workers call back into. Desired
state submitted here is what the workers reconcile into real infrastructure —
the control plane never touches AWS or Kubernetes directly.

## Run it

```bash
cd app/control-plane
uvicorn main:app --reload            # http://127.0.0.1:8000
```

- Requires a reachable PostgreSQL via `DATABASE_URL` (see configuration
  below) and migrations applied — see
  [migrations/README.md](migrations/README.md).
- The branded Swagger UI is served at [`/docs`](http://127.0.0.1:8000/docs)
  (raw schema at `/openapi.json`); `/redoc` is disabled.
- Operational CLIs for seeding users/teams live in
  [scripts/README.md](scripts/README.md).

## API surface

| Method & path | Auth | What it does |
|---|---|---|
| `POST /auth/login` | none | Authenticate, returns a JWT |
| `GET /auth/me` | JWT | Current user + team memberships |
| `POST /app/create` | JWT | Create an app: registers services, capabilities, and the desired state that drives the whole pipeline |
| `GET /app` | JWT | List apps visible to the current user (team-scoped) |
| `POST /app/{app_name}/update` | JWT | Update an existing app's desired state |
| `DELETE /app/{app_name}/envs/{env}` | JWT | Delete one environment of an app |
| `GET /app/{app_name}/status` | JWT | Per-environment rollout/infra status |
| `GET /cluster` | JWT | List registered clusters |
| `POST /cluster/register` | JWT | Register (or refresh) a cluster: endpoint, environment, worker token/CA |
| `GET /internal/requests/{request_id}` | internal key | Request snapshot for a worker (app, services, envs, per-capability cluster access) |
| `POST /internal/requests/{request_id}/status` | internal key | Worker reports its outcome |
| `GET /internal/deployment-groups/{app_name}/{env}` | internal key | An (app, env) group's services |
| `POST /internal/deployment-setup` | internal key | Health reporter records a service's ArgoCD rollout state |
| `GET /internal/clusters` | internal key | Every registered cluster with kube access (raw token/CA) — the health reporter's sweep input |
| `GET /internal/clusters/{cluster_name}` | internal key | Redacted registration info (never returns the token) |

Two trust boundaries, both enforced as middleware/dependencies:

- **User-facing routes** — JWT bearer tokens (`auth/interceptor.py`), issued
  by `/auth/login`.
- **`/internal/*`** — the `X-Internal-API-Key` header
  (`dependencies/internal.py`); only the worker Lambdas and CI hold this key.

Every response carries an `X-Request-ID` (honored from the request or
generated), which threads through the JSON logs. CORS is configured from
`ALLOWED_ORIGINS` and runs outermost so browser preflights are answered
before the auth interceptor.

## Configuration

All configuration is environment-variable based (no config files to edit):

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `database/db_engine.py`, `migrations/env.py` | `postgresql://postgres:password@127.0.0.1:5432/makeway?sslmode=require` | PostgreSQL connection |
| `ALLOWED_ORIGINS` | `main.py` | `http://localhost:5173` | Comma-separated CORS origins |
| `GITOPS_REPO_URL` | `core/config.py` | `https://github.com/kapil4457/Makeway-IDP` | The platform repo the GitOps configs live in |
| `INTERNAL_API_KEY` | `dependencies/internal.py` | unset (internal API rejects all calls) | Shared secret for `/internal/*` |
| `LOG_LEVEL`, `MAKEWAY_LOG_DIR`, `MAKEWAY_LOG_MAX_BYTES`, `MAKEWAY_LOG_BACKUPS` | `core/logger.py` | — | JSON logging setup |

## Structure

```
app/control-plane/
├── main.py                 # FastAPI app: middleware order, routers, lifespan
├── alembic.ini             # Alembic config (migrations/README.md)
├── auth/                   # JWT issuing/verification, password hashing, the auth middleware
├── controllers/            # Route handlers: app, cluster, auth, internal, swagger
├── core/                   # Logging, platform constants, exception handlers
├── database/
│   ├── db_engine.py        # Engine/session wiring from DATABASE_URL
│   └── models/             # SQLModel tables (see docs/design/Database.md)
├── dependencies/           # FastAPI Depends wiring: auth, internal key, DB session, services
├── dto/                    # Pydantic request/response schemas, per-capability configs, enums
├── exceptions/             # Error types mapped to responses by core/exception_handlers
├── migrations/             # Alembic environment + versions (migrations/README.md)
├── repository/             # Thin data-access: repositories add()+flush(), the service commits once
├── scripts/                # Operational CLIs (scripts/README.md)
├── service/                # Business logic: app create/update/delete/status, auth, cluster, internal API
├── swagger/                # Branded Swagger UI assets
└── tests/                  # Regression tests, run directly (see below)
```

**Layering rule:** a request flows `controller → service → repository`.
Repositories own `add()` + `flush()`; the service owns the single
`session.commit()`, so a multi-row write (app + services + capabilities +
request + job) is atomic — it either fully lands or fully rolls back.

## Regression tests

The tests in [tests/](tests/) are plain scripts with `__main__` blocks — run
them directly, not via pytest:

```bash
cd app/control-plane
python tests/test_internal_api_service.py     # internal API + DB regression (recreates schema)
python tests/test_app_update_service.py       # app update flow
```

`test_internal_api_service.py` drops and recreates the schema in its
`__main__`, so it needs a disposable database. `regression_check.sh` is a
separate live-server check of the OpenAPI surface and `POST /app/create`
validation:

```bash
bash regression_check.sh http://127.0.0.1:8000
```

## Further reading

- [docs/design/Database.md](../../docs/design/Database.md) — every table,
  the atomic write pattern, and the ER diagram
- [docs/design/App-Flows.md](../../docs/design/App-Flows.md) — what happens
  end-to-end after `POST /app/create`
- [docs/design/GitOps-and-CI-Pipeline.md](../../docs/design/GitOps-and-CI-Pipeline.md) —
  the delivery model the workers feed
