"""HTTP-level regression for the app-status loop — the closed write+read path.

``GET /app/{app_name}/status`` renders per-service health from
``DeploymentSetup`` rows, and those rows exist only once a reporter records
them (``POST /internal/deployment-setup``). This file drives the REAL routers,
middleware, dependency wiring, services, and serializers over the wire via
FastAPI TestClient — the layer the service-level suites cannot catch (DTO
plumbing, route registration, internal-key guard, response shape):

  1. ``GET  /app/order-service/status``        -> health ``unknown``, no deployment
       (honest before the reporter has ever fired)
  2. ``POST /internal/deployment-setup``       -> the ArgoCD health reporter's report
  3. ``GET  /app/order-service/status`` again  -> health ``healthy`` + deployment block

Only the JWT dependency (``get_current_user``) is stubbed to return the seeded
owner — auth middleware and everything downstream run for real. The internal
key guard is exercised with a real header; omit the Authorization header on the
public GET since ``AuthInterceptor`` passes requests through when it's absent.

Run directly — not under pytest — same ``drop_all``/``create_all`` pattern as
the other test files in this directory.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
# Read at import time by dependencies.internal — must be set before main loads.
os.environ["INTERNAL_API_KEY"] = "e2e-test-key-0000"

from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    """SQLite has no JSONB; render a plain JSON column instead."""
    return "JSON"


from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel, Session  # noqa: E402

import database.db_engine as db_engine  # noqa: E402
from database.models.app import App  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
from database.models.service import Service  # noqa: E402
from database.models.team import Team  # noqa: E402
from database.models.team_member import TeamMember  # noqa: E402
from database.models.user import User  # noqa: E402
from dependencies.auth import get_current_user  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
import main  # noqa: E402


def _seed() -> tuple[User, int]:
    """Team + owner + cluster(qa) + app + one service. Returns (owner, svc_id)."""
    with Session(db_engine.engine) as session:
        user = User(email="owner@makeway.dev", passwordHash="hash")
        session.add(user)
        session.flush()

        team = Team(teamName="orders-team")
        session.add(team)
        session.flush()
        session.add(TeamMember(teamId=team.teamId, userId=user.userId))

        cluster = Cluster(
            clusterName="qa-cluster",
            kubeApiEndpoint="https://k8s.qa",
            environment="qa",
        )
        session.add(cluster)
        session.flush()

        app = App(appName="order-service", teamId=team.teamId, createdBy=user.email)
        session.add(app)
        session.flush()

        svc = Service(
            svcName="orders-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster.clusterId,
            appId=app.appId,
        )
        session.add(svc)
        session.flush()

        session.commit()
        return user.userId, svc.svcId


def test_status_loop_over_http() -> None:
    owner_id, svc_id = _seed()

    # Reload the owner from a fresh session per request: the router accesses
    # current_user.userId and passes the instance into the service, so the
    # stub must hand back a Session-bound User (not a detached one from the
    # seeding session — SQLAlchemy raises DetachedInstanceError otherwise).
    def _current_user() -> User:
        # Re-select within a *kept-open* session so the instance stays bound
        # for the whole request; closing before the router touches .userId
        # would expire attributes and raise DetachedInstanceError.
        session = Session(db_engine.engine)
        return session.get(User, owner_id)

    main.app.dependency_overrides[get_current_user] = _current_user

    with TestClient(main.app) as client:
        # 1. Honest before any report: no deployment row exists yet.
        resp = client.get("/app/order-service/status")
        assert resp.status_code == 200, resp.text
        qa = resp.json()["envStatuses"][0]
        assert qa["env"] == "qa"
        assert qa["services"][0]["health"] == "unknown"
        assert qa["services"][0]["deployment"] is None

        # 2. The ArgoCD health reporter's report lands (write side), guarded by
        # the real internal-key check.
        resp = client.post(
            "/internal/deployment-setup",
            json={
                "svcId": svc_id,
                "status": "success",
                "argocdAppName": "orders-api-qa",
                "lastSyncedAt": "2026-08-30T12:00:00Z",
            },
            headers={"X-Internal-API-Key": "e2e-test-key-0000"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "success"

        # 3. The same GET now renders real health + the deployment block.
        resp = client.get("/app/order-service/status")
        assert resp.status_code == 200, resp.text
        svc = resp.json()["envStatuses"][0]["services"][0]
        assert svc["health"] == "healthy"
        assert svc["healthSource"] == "persisted"
        assert svc["deployment"]["argocdAppName"] == "orders-api-qa"
        assert svc["deployment"]["errorMessage"] is None
        assert svc["error"] is None

    main.app.dependency_overrides.clear()

    print("test_status_loop_over_http .... OK")


def _reset_db() -> None:
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_status_loop_over_http()
    print("All app-status HTTP regression tests passed.")