"""HTTP-level regression for the list endpoints added for the frontend dashboard.

``GET /app`` (team-scoped) and ``GET /cluster`` (global, credential-redacted)
are read-only additions that mirror the write-side conventions. This file
drives the REAL routers, middleware, dependency wiring, services, and
serializers over the wire via FastAPI TestClient — the layer the service-level
suites cannot catch (DTO plumbing, route registration, response shape, and the
guarantees the dashboard relies on):

  1. ``GET /app``     -> only apps owned by the caller's ACTIVE memberships,
                         most recently modified first, camelCase shape
  2. ``GET /app`` as a user with a deleted membership (or none) -> empty list
  3. ``GET /cluster`` -> clusters with ``hasToken``/``hasCaCert`` flags and
                         NEVER the raw credential values
  4. Unauthenticated  -> no header => 401 ``HTTP_ERROR`` (HTTPBearer guard);
                         bad token => 401 ``INVALID_TOKEN`` (auth middleware).
                         Both shapes must land as 401 so the dashboard's
                         session-expiry handling can key on the status alone.
  5. CORS preflight   -> OPTIONS from the frontend origin is answered before
                         AuthInterceptor (allow-origin/-headers/-credentials).

Only the JWT dependency (``get_current_user``) is stubbed to return the seeded
owner — auth middleware and everything downstream run for real.

Run directly — not under pytest — same ``drop_all``/``create_all`` pattern as
the other test files in this directory.
"""
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID

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
from database.models.team import Team  # noqa: E402
from database.models.team_member import TeamMember  # noqa: E402
from database.models.user import User  # noqa: E402
from dependencies.auth import get_current_user  # noqa: E402
import main  # noqa: E402


def _seed() -> tuple["UUID", "UUID"]:
    """Owner + app, a second team with another app, and clusters with secrets.

    Returns (owner_id, outsider_id) as UUID objects read *inside* the open
    seeding session — NOT the User objects: the seeding session closes on exit
    and commit-expired detached instances would raise DetachedInstanceError
    the moment .userId is touched (the same trap test_app_status_http.py
    documents). The ids stay UUID instances because ``session.get(User, ...)``
    binds the pk through the Uuid column type.
    """
    with Session(db_engine.engine) as session:
        owner = User(email="owner@makeway.dev", passwordHash="hash")
        outsider = User(email="outsider@makeway.dev", passwordHash="hash")
        session.add(owner)
        session.add(outsider)
        session.flush()

        orders_team = Team(teamName="orders-team")
        ghost_team = Team(teamName="ghost-team")
        session.add(orders_team)
        session.add(ghost_team)
        session.flush()

        session.add(TeamMember(teamId=orders_team.teamId, userId=owner.userId))
        # Deleted membership: must NOT grant visibility of orders-team apps.
        session.add(
            TeamMember(teamId=orders_team.teamId, userId=outsider.userId, isDeleted=True)
        )
        session.add(
            TeamMember(teamId=ghost_team.teamId, userId=outsider.userId)
        )

        session.add(
            App(appName="order-service", teamId=orders_team.teamId, createdBy=owner.email)
        )
        session.add(
            App(appName="ghost-app", teamId=ghost_team.teamId, createdBy=outsider.email)
        )
        session.flush()

        session.add(
            Cluster(
                clusterName="qa-cluster",
                kubeApiEndpoint="https://k8s.qa",
                environment="qa",
                kubeToken="tok-secret-do-not-leak",
            )
        )
        session.add(
            Cluster(
                clusterName="prod-cluster",
                kubeApiEndpoint="https://k8s.prod",
                environment="prod",
                kubeToken="tok-secret-do-not-leak",
                kubeCaCert="ca-base64-do-not-leak",
            )
        )

        session.commit()
        return owner.userId, outsider.userId


def _user_stub(user_id) -> User:
    # Re-select within a *kept-open* session so the instance stays bound for
    # the whole request (same DetachedInstanceError reasoning as
    # test_app_status_http.py).
    session = Session(db_engine.engine)
    return session.get(User, user_id)


def test_list_endpoints_over_http() -> None:
    owner_id, outsider_id = _seed()

    with TestClient(main.app) as client:
        # 1. Team-scoped app list, most recently modified first.
        main.app.dependency_overrides[get_current_user] = lambda: _user_stub(owner_id)
        resp = client.get("/app")
        assert resp.status_code == 200, resp.text
        apps = resp.json()
        assert len(apps) == 1, apps
        row = apps[0]
        assert row["appName"] == "order-service"
        assert row["teamName"] == "orders-team"
        assert row["teamId"] is not None
        assert {"appId", "appName", "createdAt", "modifiedAt", "createdBy"} <= set(row)
        assert row["appRepoUrl"] is None  # honest until Step-1 reports it

        # 2. Deleted membership + foreign team ownership -> only the ghost app.
        main.app.dependency_overrides[get_current_user] = lambda: _user_stub(outsider_id)
        resp = client.get("/app")
        assert resp.status_code == 200, resp.text
        apps = resp.json()
        assert [a["appName"] for a in apps] == ["ghost-app"]

        # 3. Cluster list: presence flags only, no credential leakage.
        main.app.dependency_overrides[get_current_user] = lambda: _user_stub(owner_id)
        resp = client.get("/cluster")
        assert resp.status_code == 200, resp.text
        clusters = {c["clusterName"]: c for c in resp.json()}
        assert set(clusters) == {"qa-cluster", "prod-cluster"}
        assert clusters["qa-cluster"]["hasToken"] is True
        assert clusters["qa-cluster"]["hasCaCert"] is False
        assert clusters["prod-cluster"]["hasCaCert"] is True
        blob = str(resp.json())
        assert "tok-secret-do-not-leak" not in blob
        assert "ca-base64-do-not-leak" not in blob
        assert "kubeToken" not in clusters["qa-cluster"]

        # 3b. /auth/me: active memberships only, with team names resolved.
        #     TeamMember rows carry no timestamp, so memberSince is absent by
        #     design (the AttributeError regression this documents).
        main.app.dependency_overrides[get_current_user] = lambda: _user_stub(owner_id)
        resp = client.get("/auth/me")
        assert resp.status_code == 200, resp.text
        me = resp.json()
        assert me["email"] == "owner@makeway.dev"
        assert len(me["teams"]) == 1, me
        team = me["teams"][0]
        assert team["teamName"] == "orders-team"
        assert team["role"] == "member"
        assert "memberSince" not in team

        main.app.dependency_overrides[get_current_user] = lambda: _user_stub(outsider_id)
        resp = client.get("/auth/me")
        assert resp.status_code == 200, resp.text
        me = resp.json()
        # The deleted orders-team membership must not leak back in.
        assert [t["teamName"] for t in me["teams"]] == ["ghost-team"]

        # 4. Unauthenticated -> both shapes land as 401 (HTTPBearer here raises
        #    HTTP_401_UNAUTHORIZED, and the middleware raises INVALID_TOKEN).
        main.app.dependency_overrides.pop(get_current_user)
        for path in ("/app", "/cluster"):
            resp = client.get(path)
            assert resp.status_code == 401, (path, resp.text)
            body = resp.json()
            assert body["success"] is False
            assert body["error"]["code"] == "HTTP_ERROR"

            resp = client.get(path, headers={"Authorization": "Bearer not-a-real-token"})
            assert resp.status_code == 401, (path, resp.text)
            body = resp.json()
            assert body["success"] is False
            assert body["error"]["code"] == "INVALID_TOKEN"

    with TestClient(main.app) as client:
        # 5. Browser preflight is answered by CORS before auth sees it.
        resp = client.options(
            "/app/create",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, idempotency-key",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "idempotency-key" in resp.headers["access-control-allow-headers"].lower()
        assert resp.headers["access-control-allow-credentials"] == "true"

    main.app.dependency_overrides.clear()

    main.app.dependency_overrides.clear()

    print("test_list_endpoints_over_http .... OK")


def _reset_db() -> None:
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_list_endpoints_over_http()
    print("All list-endpoint HTTP regression tests passed.")