"""Regression for AppDeleteService.purge_app — DELETE /app/{app_name}.

Run directly (never pytest — same harness as test_internal_api_service.py:
temp sqlite, JSONB compiled as JSON, all model modules imported before
create_all). It never touches the configured DATABASE_URL of the running
control plane.
"""

import os
import sys
import tempfile
import uuid
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
from database.models.job import Job  # noqa: E402
from database.models.request import Request  # noqa: E402
from database.models.service import Service  # noqa: E402
from database.models.team import Team  # noqa: E402
from database.models.team_member import TeamMember  # noqa: E402
from database.models.user import User  # noqa: E402
from dto.enums.job_status import JobStatus  # noqa: E402
from dto.enums.job_step import JobStep  # noqa: E402
from dto.enums.request_status import RequestStatus  # noqa: E402
from dto.enums.request_type import RequestType  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from exceptions.base import InvalidRequestException, NotFoundException  # noqa: E402
from repository.app_repository import AppRepository  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
from repository.job_repository import JobRepository  # noqa: E402
from repository.request_repository import RequestRepository  # noqa: E402
from repository.service_repository import ServiceRepository  # noqa: E402
from repository.team_repository import TeamMemberRepository  # noqa: E402
from service.app_delete_service import AppDeleteService  # noqa: E402


def _build_service(session: Session) -> AppDeleteService:
    return AppDeleteService(
        session=session,
        queue=None,  # purge_app never publishes to the queue
        teamMemberRepository=TeamMemberRepository(session),
        appRepository=AppRepository(session),
        clusterRepository=ClusterRepository(session),
        serviceRepository=ServiceRepository(session),
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
    )


def _seed(
    session: Session,
    *,
    name: str,
    request_status: RequestStatus | None = RequestStatus.SUCCESS,
    with_services: bool = False,
) -> tuple[App, User, int | None]:
    """Team + member + user + app, optional request/job and services.

    Returns (app, user, request_id) — request_id None when no request seeded.
    """
    user = User(email=f"{name}@example.com", passwordHash="x")
    team = Team(teamName=name)
    session.add(user)
    session.add(team)
    session.flush()

    session.add(TeamMember(teamId=team.teamId, userId=user.userId))

    app = App(appName=name, teamId=team.teamId)
    session.add(app)
    session.flush()

    if with_services:
        cluster = Cluster(
            clusterName=f"{name}-qa",
            kubeApiEndpoint="https://k8s.qa",
            environment="qa",
        )
        session.add(cluster)
        session.flush()
        session.add(
            Service(
                svcName=f"{name}-api-qa",
                serviceType=ServiceType.FAST_API,
                clusterId=cluster.clusterId,
                appId=app.appId,
            )
        )

    request: Request | None = None
    if request_status is not None:
        request = Request(
            idempotencyKey=uuid.uuid4().hex,
            requestType=RequestType.CREATE_APP,
            requestStatus=request_status,
            appId=app.appId,
        )
        session.add(request)
        session.flush()
        session.add(
            Job(
                requestId=request.requestId,
                step=JobStep.CREATE_PROJECT,
                status=JobStatus.SUCCESS,
            )
        )

    session.commit()
    return app, user, request.requestId if request_status is not None else None


def _count(session: Session, model, column, value) -> int:
    return len(session.exec(select(model).where(column == value)).all())


def test_purges_zombie_app() -> None:
    with Session(db_engine.engine) as session:
        app, user, request_id = _seed(session, name="zombie-app")
        service = _build_service(session)

        response = service.purge_app(app_name=app.appName, user=user, confirm=True)

        assert response.appName == app.appName
        assert response.purged == {"jobs": 1, "requests": 1, "app": 1}

        fresh = Session(db_engine.engine)
        try:
            assert _count(fresh, App, App.appName, "zombie-app") == 0
            assert _count(fresh, Request, Request.appId, app.appId) == 0
            assert _count(fresh, Job, Job.requestId, request_id) == 0
        finally:
            fresh.close()


def test_refuses_when_services_remain() -> None:
    with Session(db_engine.engine) as session:
        app, user, _ = _seed(session, name="has-services", with_services=True)
        service = _build_service(session)

        try:
            service.purge_app(app_name=app.appName, user=user, confirm=True)
        except InvalidRequestException as exc:
            assert "still has" in exc.message
        else:
            raise AssertionError("expected refusal while service rows exist")

        # Nothing was purged.
        fresh = Session(db_engine.engine)
        try:
            assert _count(fresh, App, App.appName, "has-services") == 1
            assert _count(fresh, Service, Service.appId, app.appId) == 1
        finally:
            fresh.close()


def test_refuses_in_flight_request() -> None:
    with Session(db_engine.engine) as session:
        app, user, _ = _seed(session, name="in-flight", request_status=RequestStatus.IN_PROGRESS)
        service = _build_service(session)

        try:
            service.purge_app(app_name=app.appName, user=user, confirm=True)
        except InvalidRequestException as exc:
            assert "in_progress" in exc.message
        else:
            raise AssertionError("expected refusal while a request is in flight")


def test_refuses_without_confirm() -> None:
    with Session(db_engine.engine) as session:
        app, user, _ = _seed(session, name="needs-confirm")
        service = _build_service(session)

        try:
            service.purge_app(app_name=app.appName, user=user, confirm=False)
        except InvalidRequestException as exc:
            assert "confirm" in exc.message
        else:
            raise AssertionError("expected refusal without confirm=true")

        fresh = Session(db_engine.engine)
        try:
            assert _count(fresh, App, App.appName, "needs-confirm") == 1
        finally:
            fresh.close()


def test_unknown_app_not_found() -> None:
    with Session(db_engine.engine) as session:
        _, user, _ = _seed(session, name="anyone", request_status=None)
        service = _build_service(session)

        try:
            service.purge_app(app_name="ghost", user=user, confirm=True)
        except NotFoundException:
            pass
        else:
            raise AssertionError("expected NotFoundException for an unknown app")


def test_outsider_rejected() -> None:
    with Session(db_engine.engine) as session:
        app, _, _ = _seed(session, name="owned", request_status=None)
        _, stranger, _ = _seed(session, name="stranger", request_status=None)
        service = _build_service(session)

        try:
            service.purge_app(app_name=app.appName, user=stranger, confirm=True)
        except InvalidRequestException as exc:
            assert "not a member" in exc.message
        else:
            raise AssertionError("expected refusal for a non-member")


def test_purges_app_without_requests() -> None:
    with Session(db_engine.engine) as session:
        app, user, _ = _seed(session, name="bare-app", request_status=None)
        service = _build_service(session)

        response = service.purge_app(app_name=app.appName, user=user, confirm=True)

        assert response.purged == {"app": 1}


if __name__ == "__main__":
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)

    test_purges_zombie_app()
    test_refuses_when_services_remain()
    test_refuses_in_flight_request()
    test_refuses_without_confirm()
    test_unknown_app_not_found()
    test_outsider_rejected()
    test_purges_app_without_requests()

    SQLModel.metadata.drop_all(db_engine.engine)
    db_engine.dispose_engine()

    print("test_app_delete_service: all 7 checks passed")
