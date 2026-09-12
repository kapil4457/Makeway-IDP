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
# register on SQLModel.metadata (same order constraint as the other suites).
from sqlmodel import SQLModel, Session, select  # noqa: E402

import database.db_engine as db_engine  # noqa: E402
from database.models.app import App  # noqa: E402
from database.models.capability import Capability  # noqa: E402
from database.models.capability_access import CapabilityAccess  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
from database.models.deployment_setup import DeploymentSetup  # noqa: E402
from database.models.infra_requirement import InfraRequirement  # noqa: E402
from database.models.job import Job  # noqa: E402
from database.models.request import Request  # noqa: E402
from database.models.service import Service  # noqa: E402
from database.models.team import Team  # noqa: E402
from database.models.team_member import TeamMember  # noqa: E402
from database.models.user import User  # noqa: E402
from dto.enums.capability_status import CapabilityStatus  # noqa: E402
from dto.enums.environment import Environment  # noqa: E402
from dto.enums.job_step import JobStep  # noqa: E402
from dto.enums.job_status import JobStatus  # noqa: E402
from dto.enums.request_status import RequestStatus  # noqa: E402
from dto.enums.request_type import RequestType  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from dto.request.internal import InternalStatusUpdateRequest  # noqa: E402
from exceptions.base import InvalidRequestException, NotFoundException  # noqa: E402
from repository.app_repository import AppRepository  # noqa: E402
from repository.capability_access_repository import CapabilityAccessRepository  # noqa: E402
from repository.capability_repository import CapabilityRepository  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
from repository.deployment_setup_repository import DeploymentSetupRepository  # noqa: E402
from repository.infra_requirement_repository import InfraRequirementRepository  # noqa: E402
from repository.job_repository import JobRepository  # noqa: E402
from repository.request_repository import RequestRepository  # noqa: E402
from repository.service_repository import ServiceRepository  # noqa: E402
from repository.team_repository import TeamMemberRepository  # noqa: E402
from service.app_delete_service import AppDeleteService  # noqa: E402
from service.internal_api_service import InternalApiService  # noqa: E402


class _RecordingQueue:
    """Minimal SQS-free stand-in with the AppCreationQueue.publish contract."""

    def __init__(self):
        self.published: list[dict] = []

    def publish(self, *, request_id: int, job_id: int) -> str:
        self.published.append({"request_id": request_id, "job_id": job_id})
        return "msg-id"


def _build_service(session: Session, queue: _RecordingQueue) -> AppDeleteService:
    return AppDeleteService(
        session=session,
        queue=queue,
        teamMemberRepository=TeamMemberRepository(session),
        appRepository=AppRepository(session),
        clusterRepository=ClusterRepository(session),
        serviceRepository=ServiceRepository(session),
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
    )


def _build_internal_api(session: Session) -> InternalApiService:
    return InternalApiService(
        session=session,
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
        appRepository=AppRepository(session),
        serviceRepository=ServiceRepository(session),
        clusterRepository=ClusterRepository(session),
        capabilityRepository=CapabilityRepository(session),
        capabilityAccessRepository=CapabilityAccessRepository(session),
        infraRequirementRepository=InfraRequirementRepository(session),
        deploymentSetupRepository=DeploymentSetupRepository(session),
    )


def _seed_created_app(with_extra_envs: bool = False) -> tuple[int, int, int, int]:
    """A completed app creation: team + owner + qa cluster + app + one service
    + one rel_database capability (tier 1) + SUCCESS request/job.

    ``with_extra_envs`` also registers a uat cluster with a uat service and a
    prod cluster with a prod service, so env-scoped purge tests can verify the
    other environments survive.

    Returns (app_id, svc_id, capability_id, user_id).
    """
    with Session(db_engine.engine) as session:
        team = Team(teamName="platform")
        session.add(team)
        session.flush()

        user = User(email="owner@makeway.io", passwordHash="x")
        session.add(user)
        session.flush()
        session.add(
            TeamMember(teamId=team.teamId, userId=user.userId, isDeleted=False)
        )

        cluster_qa = Cluster(
            clusterName="qa-cluster",
            kubeApiEndpoint="https://k8s.qa",
            kubeToken="qa-token",
            kubeCaCert="qa-ca",
            environment="qa",
        )
        session.add(cluster_qa)
        session.flush()

        cluster_uat = None
        cluster_prod = None
        if with_extra_envs:
            cluster_uat = Cluster(
                clusterName="uat-cluster",
                kubeApiEndpoint="https://k8s.uat",
                kubeToken="uat-token",
                kubeCaCert="uat-ca",
                environment="uat",
            )
            cluster_prod = Cluster(
                clusterName="prod-cluster",
                kubeApiEndpoint="https://k8s.prod",
                kubeToken="prod-token",
                kubeCaCert="prod-ca",
                environment="prod",
            )
            session.add(cluster_uat)
            session.add(cluster_prod)
            session.flush()

        app = App(appName="order-service", teamId=team.teamId)
        session.add(app)
        session.flush()

        svc = Service(
            svcName="orders-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster_qa.clusterId,
            appId=app.appId,
        )
        session.add(svc)
        session.flush()
        session.add(DeploymentSetup(serviceId=svc.svcId, status="success"))

        if with_extra_envs:
            session.add(
                Service(
                    svcName="orders-api-uat",
                    serviceType=ServiceType.FAST_API,
                    clusterId=cluster_uat.clusterId,
                    appId=app.appId,
                )
            )
            session.add(
                Service(
                    svcName="payment-prod",
                    serviceType=ServiceType.NODE_JS,
                    clusterId=cluster_prod.clusterId,
                    appId=app.appId,
                )
            )

        cap = Capability(capabilityType="rel_database", status=CapabilityStatus.SUCCESS)
        session.add(cap)
        session.flush()
        session.add(CapabilityAccess(capabilityId=cap.capabilityId, serviceId=svc.svcId))
        session.add(
            InfraRequirement(
                capabilityId=cap.capabilityId,
                config={"type": "rel_database", "name": "orders", "capacity": 1},
            )
        )

        req = Request(
            idempotencyKey="create-key-1",
            requestType=RequestType.CREATE_APP,
            requestStatus=RequestStatus.SUCCESS,
            appId=app.appId,
            rawRequest={"app_name": "order-service"},
        )
        session.add(req)
        session.flush()
        session.add(
            Job(requestId=req.requestId, step=JobStep.CREATE_PROJECT, status=JobStatus.SUCCESS)
        )
        session.commit()

        return (app.appId, svc.svcId, cap.capabilityId, user.userId)


def test_delete_submits_without_touching_rows() -> None:
    app_id, svc_id, cap_id, _user_id = _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="order-service",
            env=Environment.QA,
            user=user,
            idempotency_key="delete-key-1",
        )

    assert response.status == "pending"
    assert response.message == "App delete request accepted"

    with Session(db_engine.engine) as session:
        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.DELETE_APP
        assert request.requestStatus == RequestStatus.PENDING
        assert request.appId == app_id
        assert request.rawRequest == {"app_name": "order-service", "env": "qa"}

        job = session.get(Job, response.job_id)
        assert job.requestId == response.request_id
        assert job.step == JobStep.CREATE_PROJECT
        assert job.status == JobStatus.PENDING

        # Desired state stays fully intact at submit — the purge is on SUCCESS.
        assert len(session.exec(select(Service)).all()) == 1
        assert len(session.exec(select(Capability)).all()) == 1
        assert len(session.exec(select(InfraRequirement)).all()) == 1
        assert len(session.exec(select(CapabilityAccess)).all()) == 1
        assert len(session.exec(select(DeploymentSetup)).all()) == 1

        assert queue.published == [
            {"request_id": response.request_id, "job_id": response.job_id}
        ]


def test_delete_purges_env_rows_on_success() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app(with_extra_envs=True)

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()
        response = service.submit(
            app_name="order-service",
            env=Environment.QA,
            user=user,
            idempotency_key="delete-key-1",
        )

    assert response.message == "App delete request accepted"
    with Session(db_engine.engine) as session:
        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.DELETE_APP
        assert request.rawRequest == {"app_name": "order-service", "env": "qa"}
        assert request.appId == app_id

        # The worker's success callback runs the env purge in the same commit.
        api = _build_internal_api(session)
        api.update_request_status(
            response.request_id,
            InternalStatusUpdateRequest(jobId=response.job_id, status="success"),
        )

        # qa rows are gone (service, its rollout row, the qa capability set).
        assert len(session.exec(select(Service)).all()) == 2  # uat + prod remain
        assert [s.svcName for s in session.exec(select(Service)).all()] == [
            "orders-api-uat", "payment-prod",
        ]
        assert len(session.exec(select(DeploymentSetup)).all()) == 0
        assert len(session.exec(select(Capability)).all()) == 0
        assert len(session.exec(select(InfraRequirement)).all()) == 0
        assert len(session.exec(select(CapabilityAccess)).all()) == 0

        # The app record, team, user and the audit rows all stay.
        assert session.get(App, app_id) is not None
        assert session.get(Request, response.request_id).requestStatus == RequestStatus.SUCCESS

        # The read side reports the surviving envs only.
        details = api.get_request_details(response.request_id)
        assert [s["svcName"] for s in details["services"]] == [
            "orders-api-uat", "payment-prod",
        ]
        assert sorted(details["environments"]) == ["prod", "uat"]


def test_delete_last_env_leaves_only_the_app_record() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()
        response = service.submit(
            app_name="order-service",
            env=Environment.QA,
            user=user,
            idempotency_key="delete-last-key-1",
        )

    with Session(db_engine.engine) as session:
        api = _build_internal_api(session)
        api.update_request_status(
            response.request_id,
            InternalStatusUpdateRequest(jobId=response.job_id, status="success"),
        )

        # Every desired-state row went; the app record survives (documented
        # decision: strip the app fully, keep the record).
        assert len(session.exec(select(Service)).all()) == 0
        assert len(session.exec(select(Capability)).all()) == 0
        assert len(session.exec(select(InfraRequirement)).all()) == 0
        assert len(session.exec(select(CapabilityAccess)).all()) == 0
        assert session.get(App, app_id) is not None


def test_delete_idempotent_replay() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        first = service.submit(
            app_name="order-service",
            env=Environment.QA,
            user=user,
            idempotency_key="delete-key-replay",
        )
        replay = service.submit(
            app_name="order-service",
            env=Environment.QA,
            user=user,
            idempotency_key="delete-key-replay",
        )

    assert replay.request_id == first.request_id
    assert replay.job_id == first.job_id
    assert replay.status == first.status
    assert replay.message == "App delete request already exists"
    assert queue.published == [
        {"request_id": first.request_id, "job_id": first.job_id}
    ]
    assert len(session.exec(select(Request)).all()) == 2  # seed create + delete


def test_delete_rejected_while_request_in_flight() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    with Session(db_engine.engine) as session:
        session.add(
            Request(
                idempotencyKey="inflight-key",
                requestType=RequestType.UPDATE_APP,
                requestStatus=RequestStatus.PENDING,
                appId=app_id,
            )
        )
        session.commit()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()
        try:
            service.submit(
                app_name="order-service",
                env=Environment.QA,
                user=user,
                idempotency_key="blocked-key-1",
            )
            raise AssertionError("in-flight app should reject the delete")
        except InvalidRequestException:
            pass
        assert queue.published == []


def test_delete_negative_paths() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        # Unknown app -> 404.
        try:
            service.submit("no-such-app", Environment.QA, user, "neg-key-1")
            raise AssertionError("unknown app should raise NotFoundException")
        except NotFoundException:
            pass

        # Non-owner -> 400.
        try:
            service.submit(
                "order-service", Environment.QA,
                User(email="stranger@makeway.io", passwordHash="x"),
                "neg-key-2",
            )
            raise AssertionError("non-member should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # Unregistered environment -> 400.
        try:
            service.submit("order-service", Environment.UAT, user, "neg-key-3")
            raise AssertionError("unregistered env should raise InvalidRequestException")
        except InvalidRequestException as exc:
            assert "uat" in exc.message

        # Registered environment the app has no services in -> 400.
        with Session(db_engine.engine) as seed_session:
            cluster = Cluster(
                clusterName="uat-cluster",
                kubeApiEndpoint="https://k8s.uat",
                kubeToken="uat-token",
                kubeCaCert="uat-ca",
                environment="uat",
            )
            seed_session.add(cluster)
            seed_session.commit()

        try:
            service.submit("order-service", Environment.UAT, user, "neg-key-4")
            raise AssertionError("env without services should raise")
        except InvalidRequestException as exc:
            assert "no services" in exc.message

        # Prod without confirm -> 400 (even though the app HAS no prod rows,
        # the confirm gate reads first as the destructive-intent guard).
        with Session(db_engine.engine) as seed_session:
            cluster = seed_session.exec(
                select(Cluster).where(Cluster.environment == "prod")
            ).first()
            if cluster is None:
                cluster = Cluster(
                    clusterName="prod-cluster",
                    kubeApiEndpoint="https://k8s.prod",
                    kubeToken="prod-token",
                    kubeCaCert="prod-ca",
                    environment="prod",
                )
                seed_session.add(cluster)
                seed_session.flush()
                seed_session.add(
                    Service(
                        svcName="payment-prod",
                        serviceType=ServiceType.NODE_JS,
                        clusterId=cluster.clusterId,
                        appId=app_id,
                    )
                )
                seed_session.commit()

        try:
            service.submit(
                "order-service", Environment.PROD, user, "neg-key-4b"
            )
            raise AssertionError("prod delete without confirm should raise")
        except InvalidRequestException as exc:
            assert "confirm=true" in exc.message

        assert queue.published == []
        # Nothing was written by any rejected attempt (only the seeded rows:
        # the create request, and the qa + prod services).
        assert len(session.exec(select(Request)).all()) == 1
        assert len(session.exec(select(Service)).all()) == 2


def test_delete_prod_with_confirm_accepted() -> None:
    _seed_created_app(with_extra_envs=True)

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="order-service",
            env=Environment.PROD,
            user=user,
            idempotency_key="prod-confirm-key-1",
            confirm=True,
        )

    assert response.status == "pending"
    with Session(db_engine.engine) as session:
        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.DELETE_APP
        assert request.rawRequest["env"] == "prod"

        api = _build_internal_api(session)
        api.update_request_status(
            response.request_id,
            InternalStatusUpdateRequest(jobId=response.job_id, status="success"),
        )

        # prod went; qa/uat remain.
        assert sorted(s.svcName for s in session.exec(select(Service)).all()) == [
            "orders-api-qa", "orders-api-uat",
        ]


def _reset_db() -> None:
    """Fresh database per test (unique keys collide on a shared file)."""
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_delete_submits_without_touching_rows()
    print("test_delete_submits_without_touching_rows .... OK")

    _reset_db()
    test_delete_purges_env_rows_on_success()
    print("test_delete_purges_env_rows_on_success .... OK")

    _reset_db()
    test_delete_last_env_leaves_only_the_app_record()
    print("test_delete_last_env_leaves_only_the_app_record .... OK")

    _reset_db()
    test_delete_idempotent_replay()
    print("test_delete_idempotent_replay .... OK")

    _reset_db()
    test_delete_rejected_while_request_in_flight()
    print("test_delete_rejected_while_request_in_flight .... OK")

    _reset_db()
    test_delete_negative_paths()
    print("test_delete_negative_paths .... OK")

    _reset_db()
    test_delete_prod_with_confirm_accepted()
    print("test_delete_prod_with_confirm_accepted .... OK")

    print("All AppDeleteService tests passed.")
