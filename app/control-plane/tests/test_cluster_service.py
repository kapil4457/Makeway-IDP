"""Regression for ClusterService.update_cluster / delete_cluster —
PUT /cluster/{id} and DELETE /cluster/{id}.

Run directly (never pytest — same harness as test_internal_api_service.py:
temp sqlite, JSONB compiled as JSON, all model modules imported before
create_all). It never touches the configured DATABASE_URL of the running
control plane.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):
    """SQLite has no JSONB; render a plain JSON column instead."""
    return "JSON"


# Every model module must be imported before create_all so the tables
# register on SQLModel.metadata.
from sqlmodel import SQLModel, Session, select  # noqa: E402

import database.db_engine as db_engine  # noqa: E402
from database.models.app import App  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
from database.models.service import Service  # noqa: E402
from database.models.team import Team  # noqa: E402
from database.models.user import User  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from exceptions.base import ConflictException, NotFoundException  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
from repository.service_repository import ServiceRepository  # noqa: E402
from service.cluster_service import ClusterService  # noqa: E402
from dto.request.update_cluster import ClusterUpdateRequest  # noqa: E402


def _build_service(session: Session) -> ClusterService:
    return ClusterService(
        ClusterRepository(session),
        ServiceRepository(session),
    )


def _seed_cluster(
    session: Session,
    *,
    name: str,
    environment: str,
    token: str | None = "tok-1",
    ca: str | None = "ca-1",
) -> Cluster:
    cluster = Cluster(
        clusterName=name,
        kubeApiEndpoint="https://old.example.com:6443",
        environment=environment,
        kubeToken=token,
        kubeCaCert=ca,
        createdBy="seeder@example.com",
        modifiedBy="seeder@example.com",
    )
    session.add(cluster)
    session.commit()
    return cluster


def _seed_user(session: Session, name: str) -> User:
    user = User(email=f"{name}@example.com", passwordHash="x")
    session.add(user)
    session.commit()
    return user


def _seed_service_on_cluster(session: Session, cluster: Cluster, *, app_name: str) -> Service:
    """A service row pointing at the cluster — an app/team behind it, since
    Service carries NOT NULL FKs to both."""
    user = User(email=f"{app_name}@example.com", passwordHash="x")
    team = Team(teamName=app_name)
    session.add(user)
    session.add(team)
    session.flush()
    app = App(appName=app_name, teamId=team.teamId)
    session.add(app)
    session.flush()
    service = Service(
        svcName=f"{app_name}-api",
        serviceType=ServiceType.FAST_API,
        clusterId=cluster.clusterId,
        appId=app.appId,
    )
    session.add(service)
    session.commit()
    return service


def _cluster_count(session: Session, name: str) -> int:
    return len(session.exec(select(Cluster).where(Cluster.clusterName == name)).all())


def test_update_endpoint_only_keeps_credentials() -> None:
    with Session(db_engine.engine) as session:
        cluster = _seed_cluster(session, name="tunnel-qa", environment="qa")
        user = _seed_user(session, "op-endpoint")
        service = _build_service(session)

        updated = service.update_cluster(
            cluster_id=cluster.clusterId,
            request=ClusterUpdateRequest(kubeApiEndpoint="https://new.example.com:6443"),
            current_user=user,
        )

        # HttpUrl normalizes the empty path to a trailing slash — the same
        # convention register stores.
        assert updated.kubeApiEndpoint == "https://new.example.com:6443/"
        assert updated.clusterName == "tunnel-qa"
        assert updated.modifiedBy == user.email
        # None never wipes: token/CA must survive an endpoint-only patch.
        assert updated.hasToken is True
        assert updated.hasCaCert is True

        fresh = Session(db_engine.engine)
        try:
            stored = fresh.exec(select(Cluster).where(Cluster.clusterId == cluster.clusterId)).one()
            assert stored.kubeToken == "tok-1"
            assert stored.kubeCaCert == "ca-1"
        finally:
            fresh.close()


def test_update_rename_with_conflict_refused() -> None:
    with Session(db_engine.engine) as session:
        alpha = _seed_cluster(session, name="alpha", environment="qa")
        _seed_cluster(session, name="beta", environment="uat")
        user = _seed_user(session, "op-rename")
        service = _build_service(session)

        try:
            service.update_cluster(
                cluster_id=alpha.clusterId,
                request=ClusterUpdateRequest(clusterName="beta"),
                current_user=user,
            )
        except ConflictException as exc:
            assert exc.error_code == "CLUSTER_NAME_CONFLICT"
        else:
            raise AssertionError("expected refusal to rename onto an occupied name")

        # Renaming to the cluster's own name is a no-op, not a conflict.
        same = service.update_cluster(
            cluster_id=alpha.clusterId,
            request=ClusterUpdateRequest(clusterName="alpha"),
            current_user=user,
        )
        assert same.clusterName == "alpha"


def test_update_unknown_cluster_not_found() -> None:
    with Session(db_engine.engine) as session:
        user = _seed_user(session, "op-404")
        service = _build_service(session)

        try:
            service.update_cluster(
                cluster_id=9999,
                request=ClusterUpdateRequest(kubeApiEndpoint="https://x.example.com"),
                current_user=user,
            )
        except NotFoundException:
            pass
        else:
            raise AssertionError("expected NotFoundException for an unknown cluster")


def test_delete_refused_while_services_remain() -> None:
    with Session(db_engine.engine) as session:
        cluster = _seed_cluster(session, name="busy-prod", environment="prod")
        _seed_service_on_cluster(session, cluster, app_name="busy-app")
        user = _seed_user(session, "op-busy")
        service = _build_service(session)

        try:
            service.delete_cluster(cluster_id=cluster.clusterId, current_user=user)
        except ConflictException as exc:
            assert exc.error_code == "CLUSTER_IN_USE"
            assert "still serves" in exc.message
        else:
            raise AssertionError("expected refusal while service rows deploy to the cluster")

        fresh = Session(db_engine.engine)
        try:
            assert _cluster_count(fresh, "busy-prod") == 1
        finally:
            fresh.close()


def test_delete_frees_environment() -> None:
    with Session(db_engine.engine) as session:
        cluster = _seed_cluster(session, name="spare-uat", environment="uat", token=None, ca=None)
        user = _seed_user(session, "op-spare")
        service = _build_service(session)

        response = service.delete_cluster(cluster_id=cluster.clusterId, current_user=user)

        assert response.clusterName == "spare-uat"
        assert response.environment == "uat"

        fresh = Session(db_engine.engine)
        try:
            assert _cluster_count(fresh, "spare-uat") == 0
        finally:
            fresh.close()


def test_delete_unknown_cluster_not_found() -> None:
    with Session(db_engine.engine) as session:
        user = _seed_user(session, "op-del-404")
        service = _build_service(session)

        try:
            service.delete_cluster(cluster_id=9999, current_user=user)
        except NotFoundException:
            pass
        else:
            raise AssertionError("expected NotFoundException for an unknown cluster")


if __name__ == "__main__":
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)

    test_update_endpoint_only_keeps_credentials()
    test_update_rename_with_conflict_refused()
    test_update_unknown_cluster_not_found()
    test_delete_refused_while_services_remain()
    test_delete_frees_environment()
    test_delete_unknown_cluster_not_found()

    SQLModel.metadata.drop_all(db_engine.engine)
    db_engine.dispose_engine()

    print("test_cluster_service: all 6 checks passed")
