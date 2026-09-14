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
from database.models.deployment_setup import DeploymentSetup  # noqa: E402
from database.models.capability_access import CapabilityAccess  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
from database.models.infra_requirement import InfraRequirement  # noqa: E402
from database.models.job import Job  # noqa: E402
from database.models.request import Request  # noqa: E402
from database.models.service import Service  # noqa: E402
from database.models.team import Team  # noqa: E402
from database.models.team_member import TeamMember  # noqa: E402
from database.models.user import User  # noqa: E402
# The DTO class is also named Capability — alias it to keep both importable.
from dto.configs.capability import Capability as CapabilityDto  # noqa: E402
from dto.configs.database_config import DatabaseConfig  # noqa: E402
from dto.configs.env_config import CapabilityAccessPatch, EnvConfig  # noqa: E402
from dto.configs.messaging_config import MessagingConfig  # noqa: E402
from dto.configs.queue_config import QueueConfig  # noqa: E402
from dto.configs.service_config import ServiceConfig  # noqa: E402
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
from service.app_update_service import AppUpdateService  # noqa: E402
from service.internal_api_service import InternalApiService  # noqa: E402


class _RecordingQueue:
    """Minimal SQS-free stand-in with the AppCreationQueue.publish contract."""

    def __init__(self):
        self.published: list[dict] = []

    def publish(self, *, request_id: int, job_id: int) -> str:
        self.published.append({"request_id": request_id, "job_id": job_id})
        return "msg-id"


def _build_service(session: Session, queue: _RecordingQueue) -> AppUpdateService:
    return AppUpdateService(
        session=session,
        queue=queue,
        teamMemberRepository=TeamMemberRepository(session),
        appRepository=AppRepository(session),
        clusterRepository=ClusterRepository(session),
        serviceRepository=ServiceRepository(session),
        capabilityRepository=CapabilityRepository(session),
        infraRequirementRepository=InfraRequirementRepository(session),
        capabilityAccessRepository=CapabilityAccessRepository(session),
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


def _seed_created_app() -> tuple[int, int, int, int]:
    """A completed app creation: team + owner + qa cluster + app + one service
    + one rel_database capability (tier 1) + SUCCESS request/job.

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

        cap = Capability(capabilityType="rel_database", status=CapabilityStatus.PENDING)
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


def _db_update(
    capacity: int = 5,
    extra_caps: list | None = None,
    services: list | None = None,
    env: Environment = Environment.QA,
) -> list[EnvConfig]:
    """A one-env update: grow the database tier + optionally add caps/services."""
    capabilities = [
        CapabilityDto(
            config=DatabaseConfig(name="orders", username="orders_admin", capacity=capacity),
            access_to=["orders-api"],
        )
    ] + (extra_caps or [])
    return [EnvConfig(env=env, services=services or [], capabilities=capabilities)]


def test_update_grows_database_and_adds_messaging() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="order-service",
            updates=_db_update(
                capacity=5,
                extra_caps=[
                    CapabilityDto(
                        config=MessagingConfig(queue=[QueueConfig(name="events")]),
                        access_to=["orders-api"],
                    )
                ],
            ),
            user=user,
            idempotency_key="update-key-1",
        )

    assert response.status == "pending"
    assert response.message == "App update request accepted"

    with Session(db_engine.engine) as session:
        # The rel_database capability was MODIFIED, not duplicated.
        caps = session.exec(select(Capability).order_by(Capability.capabilityId)).all()
        assert [c.capabilityType for c in caps] == ["rel_database", "messaging"]

        db_cap = caps[0]
        assert db_cap.status == CapabilityStatus.PENDING  # reset for reconciliation
        assert db_cap.errorMessage is None
        assert db_cap.modifiedBy == "owner@makeway.io"

        infra = session.exec(
            select(InfraRequirement).order_by(InfraRequirement.infraRequirementId)
        ).all()
        assert [i.capabilityId for i in infra] == [caps[0].capabilityId, caps[1].capabilityId]
        # Tier 5 -> 50GB once Crossplane reconciles (composition: 10GB per tier).
        assert infra[0].config["capacity"] == 5
        assert infra[0].config["name"] == "orders"
        assert infra[0].config["type"] == "rel_database"

        # Messaging capability was ADDED with its own infra requirement.
        assert infra[1].config["type"] == "messaging"

        # One access binding per capability, both to the existing service.
        accesses = session.exec(select(CapabilityAccess)).all()
        assert {(a.capabilityId, a.serviceId) for a in accesses} == {
            (caps[0].capabilityId, 1),
            (caps[1].capabilityId, 1),
        }

        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.UPDATE_APP
        assert request.requestStatus == RequestStatus.PENDING
        assert request.appId == 1
        assert request.rawRequest["app_name"] == "order-service"
        assert request.rawRequest["updates"][0]["env"] == "qa"

        job = session.get(Job, response.job_id)
        assert job.requestId == response.request_id
        assert job.step == JobStep.CREATE_PROJECT
        assert job.status == JobStatus.PENDING

        # Enqueued exactly once, after the commit, with the new ids.
        assert queue.published == [
            {"request_id": response.request_id, "job_id": response.job_id}
        ]

        # The read side (what the workers consume) returns the MERGED state:
        # full service list, all capabilities incl. the new one.
        api = _build_internal_api(session)
        details = api.get_request_details(response.request_id)
        assert [s["svcName"] for s in details["services"]] == ["orders-api-qa"]
        assert details["environments"] == ["qa"]
        assert [c["capabilityType"] for c in details["capabilities"]] == [
            "rel_database", "messaging",
        ]
        assert details["capabilities"][0]["config"]["capacity"] == 5
        assert details["capabilities"][1]["environment"] == "qa"
        assert details["capabilities"][1]["namespace"] == "order-service-qa"


def test_update_adds_service_and_grants_access() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        service.submit(
            app_name="order-service",
            updates=[
                EnvConfig(
                    env=Environment.QA,
                    services=[ServiceConfig(service_type=ServiceType.NODE_JS,
                                            service_name="payment")],
                    capabilities=[
                        CapabilityDto(
                            config=MessagingConfig(queue=[QueueConfig(name="events")]),
                            access_to=["payment"],
                        )
                    ],
                )
            ],
            user=user,
            idempotency_key="update-key-2",
        )

    with Session(db_engine.engine) as session:
        services = session.exec(select(Service).order_by(Service.svcId)).all()
        assert [s.svcName for s in services] == ["orders-api-qa", "payment-qa"]
        assert services[1].serviceType == ServiceType.NODE_JS

        caps = session.exec(select(Capability).order_by(Capability.capabilityId)).all()
        messaging = [c for c in caps if c.capabilityType == "messaging"][0]
        payment_access = [
            a for a in session.exec(select(CapabilityAccess)).all()
            if a.capabilityId == messaging.capabilityId
        ]
        assert payment_access[0].serviceId == services[1].svcId


def test_idempotent_replay_returns_original_request() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        first = service.submit(
            app_name="order-service",
            updates=_db_update(),
            user=user,
            idempotency_key="update-key-replay",
        )
        # Retrying with the same key never duplicates: the replay returns the
        # original ids and enqueues nothing.
        replay = service.submit(
            app_name="order-service",
            updates=_db_update(),
            user=user,
            idempotency_key="update-key-replay",
        )

    assert replay.request_id == first.request_id
    assert replay.job_id == first.job_id
    assert replay.status == first.status
    assert replay.message == "App update request already exists"
    assert queue.published == [
        {"request_id": first.request_id, "job_id": first.job_id}
    ]
    assert len(session.exec(select(Request)).all()) == 2  # seed create + update


def test_rejected_while_request_in_flight() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    with Session(db_engine.engine) as session:
        # Latest request back to PENDING (a create still reconciling).
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
                updates=_db_update(),
                user=user,
                idempotency_key="blocked-key-1",
            )
            raise AssertionError("in-flight app should reject the update")
        except InvalidRequestException:
            pass
        assert queue.published == []


def test_negative_paths() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()
        stranger = User(email="stranger@makeway.io", passwordHash="x")

        # Unknown app -> 404.
        try:
            service.submit("no-such-app", _db_update(), user, "neg-key-1")
            raise AssertionError("unknown app should raise NotFoundException")
        except NotFoundException:
            pass

        # Non-owner -> 400.
        try:
            service.submit("order-service", _db_update(), stranger, "neg-key-2")
            raise AssertionError("non-member should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # Empty payload -> 400.
        try:
            service.submit("order-service", [], user, "neg-key-3")
            raise AssertionError("empty updates should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # Duplicate env entries -> 400.
        try:
            service.submit(
                "order-service", _db_update() + _db_update(), user, "neg-key-4"
            )
            raise AssertionError("duplicate env should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # Unregistered environment -> 400.
        try:
            service.submit(
                "order-service",
                _db_update(env=Environment.PROD),
                user,
                "neg-key-5",
            )
            raise AssertionError("unregistered env should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # Empty access_to -> 400 (create tolerates it; update must not).
        try:
            service.submit(
                "order-service",
                [EnvConfig(
                    env=Environment.QA,
                    capabilities=[CapabilityDto(
                        config=DatabaseConfig(name="orders"), access_to=[]
                    )],
                )],
                user,
                "neg-key-6",
            )
            raise AssertionError("empty access_to should raise InvalidRequestException")
        except InvalidRequestException:
            pass

        # access_to naming a service the env doesn't have -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(
                    env=Environment.QA,
                    capabilities=[CapabilityDto(
                        config=MessagingConfig(queue=[QueueConfig(name="q")]),
                        access_to=["ghost-service"],
                    )],
                )],
                user,
                "neg-key-7",
            )
            raise AssertionError("unknown access_to service should raise")
        except InvalidRequestException:
            pass

        # Nothing was written by any rejected attempt (only the seeded rows).
        assert len(session.exec(select(Request)).all()) == 1
        assert len(session.exec(select(Capability)).all()) == 1
        assert len(session.exec(select(Service)).all()) == 1
        assert len(queue.published) == 0


def _removal_updates(
    remove_services: list[str] | None = None,
    remove_capabilities: list[str] | None = None,
    env: Environment = Environment.QA,
) -> list[EnvConfig]:
    """A one-env update that only removes (services/capabilities untouched)."""
    return [
        EnvConfig(
            env=env,
            remove_services=remove_services or [],
            remove_capabilities=remove_capabilities or [],
        )
    ]


def _report_success(request_id: int, job_id: int) -> None:
    """Drive the pipeline's success callback through the internal API."""
    with Session(db_engine.engine) as session:
        api = _build_internal_api(session)
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(jobId=job_id, status="success"),
        )


def test_update_removes_capability_and_purges_on_success() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="order-service",
            updates=_removal_updates(remove_capabilities=["rel_database"]),
            user=user,
            idempotency_key="remove-cap-key-1",
        )

    with Session(db_engine.engine) as session:
        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.UPDATE_APP
        entry = request.rawRequest["updates"][0]
        assert entry["remove_capabilities"] == ["rel_database"]
        assert entry["remove_services"] == []

        # Removal rows survive the submit — every retry must be able to
        # re-derive the XR names to tear down.
        assert len(session.exec(select(Capability)).all()) == 1
        assert len(session.exec(select(InfraRequirement)).all()) == 1
        assert len(session.exec(select(CapabilityAccess)).all()) == 1

    _report_success(response.request_id, response.job_id)

    with Session(db_engine.engine) as session:
        # Success purged the capability's rows (children first, FK-safe).
        assert len(session.exec(select(Capability)).all()) == 0
        assert len(session.exec(select(InfraRequirement)).all()) == 0
        assert len(session.exec(select(CapabilityAccess)).all()) == 0
        # The service row is untouched.
        assert [s.svcName for s in session.exec(select(Service)).all()] == ["orders-api-qa"]
        # Request/job survive as the audit trail.
        assert session.get(Request, response.request_id).requestStatus == RequestStatus.SUCCESS


def test_update_removes_service_and_capability_together() -> None:
    app_id, svc_id, cap_id, _user_id = _seed_created_app()

    with Session(db_engine.engine) as session:
        session.add(DeploymentSetup(serviceId=svc_id, status="success"))
        session.commit()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="order-service",
            updates=_removal_updates(
                remove_services=["orders-api"],
                remove_capabilities=["rel_database"],
            ),
            user=user,
            idempotency_key="remove-both-key-1",
        )

    _report_success(response.request_id, response.job_id)

    with Session(db_engine.engine) as session:
        # The whole env-scoped item set is gone, including the rollout rows.
        assert len(session.exec(select(Service)).all()) == 0
        assert len(session.exec(select(Capability)).all()) == 0
        assert len(session.exec(select(InfraRequirement)).all()) == 0
        assert len(session.exec(select(CapabilityAccess)).all()) == 0
        assert len(session.exec(select(DeploymentSetup)).all()) == 0
        # The app record itself stays.
        assert session.get(App, app_id) is not None


def test_orphaned_capability_rejects_service_removal() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        # orders-api is rel_database's only accessor in qa — removing it would
        # orphan the capability; the update must name the capability too.
        try:
            service.submit(
                app_name="order-service",
                updates=_removal_updates(remove_services=["orders-api"]),
                user=user,
                idempotency_key="orphan-key-1",
            )
            raise AssertionError("orphaning removal should raise InvalidRequestException")
        except InvalidRequestException as exc:
            assert "rel_database" in exc.message

        assert queue.published == []
        assert len(session.exec(select(Request)).all()) == 1
        assert len(session.exec(select(CapabilityAccess)).all()) == 1


def test_update_removal_negative_paths() -> None:
    _seed_created_app()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        # Service added and removed in the same delta -> 400.
        try:
            service.submit(
                "order-service",
                [
                    EnvConfig(
                        env=Environment.QA,
                        services=[ServiceConfig(
                            service_type=ServiceType.FAST_API, service_name="payment"
                        )],
                        remove_services=["payment"],
                    )
                ],
                user,
                "overlap-key-1",
            )
            raise AssertionError("overlap should raise InvalidRequestException")
        except InvalidRequestException as exc:
            assert "added and removed" in exc.message

        # A capability granting access to a removed service -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(
                    env=Environment.QA,
                    capabilities=[CapabilityDto(
                        config=MessagingConfig(queue=[QueueConfig(name="events")]),
                        access_to=["orders-api"],
                    )],
                    remove_services=["orders-api"],
                )],
                user,
                "grant-key-2",
            )
            raise AssertionError("grant to removed service should raise")
        except InvalidRequestException as exc:
            assert "orders-api" in exc.message

        # Unknown service in remove_services -> 400.
        try:
            service.submit(
                "order-service",
                _removal_updates(remove_services=["ghost"]),
                user,
                "ghost-key-3",
            )
            raise AssertionError("unknown removal service should raise")
        except InvalidRequestException as exc:
            assert "ghost" in exc.message

        # Capability type the app doesn't have in qa -> 400.
        try:
            service.submit(
                "order-service",
                _removal_updates(remove_capabilities=["messaging"]),
                user,
                "nope-key-4",
            )
            raise AssertionError("removing an absent capability should raise")
        except InvalidRequestException as exc:
            assert "messaging" in exc.message

        # Unknown capability type -> 400.
        try:
            service.submit(
                "order-service",
                _removal_updates(remove_capabilities=["bogus_type"]),
                user,
                "bogus-key-5",
            )
            raise AssertionError("unknown capability type should raise")
        except InvalidRequestException as exc:
            assert "Unknown capability type" in exc.message

        assert queue.published == []
        # Nothing was written by any rejected attempt (only the seeded rows).
        assert len(session.exec(select(Request)).all()) == 1
        assert len(session.exec(select(Capability)).all()) == 1
        assert len(session.exec(select(Service)).all()) == 1


def test_prod_removal_requires_confirm() -> None:
    app_id, _svc, _cap, _user_id = _seed_created_app()

    with Session(db_engine.engine) as session:
        cluster = Cluster(
            clusterName="prod-cluster",
            kubeApiEndpoint="https://k8s.prod",
            kubeToken="prod-token",
            kubeCaCert="prod-ca",
            environment="prod",
        )
        session.add(cluster)
        session.flush()
        session.add(
            Service(
                svcName="payment-prod",
                serviceType=ServiceType.NODE_JS,
                clusterId=cluster.clusterId,
                appId=app_id,
            )
        )
        session.commit()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        updates = [EnvConfig(env=Environment.PROD, remove_services=["payment"])]
        try:
            service.submit("order-service", updates, user, "prod-key-1")
            raise AssertionError("prod removal without confirm should raise")
        except InvalidRequestException as exc:
            assert "confirm=true" in exc.message

        response = service.submit(
            "order-service", updates, user, "prod-key-2", confirm=True
        )

    assert response.status == "pending"
    with Session(db_engine.engine) as session:
        request = session.get(Request, response.request_id)
        assert request.rawRequest["updates"][0]["remove_services"] == ["payment"]


def test_access_patch_replaces_bindings() -> None:
    app_id, _svc, cap_id, _user_id = _seed_created_app()

    # A second service the patch can grant access to.
    with Session(db_engine.engine) as session:
        cluster = session.exec(
            select(Cluster).where(Cluster.environment == "qa")
        ).first()
        session.add(
            Service(
                svcName="payment-qa",
                serviceType=ServiceType.NODE_JS,
                clusterId=cluster.clusterId,
                appId=app_id,
            )
        )
        session.commit()

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            "order-service",
            [EnvConfig(
                env=Environment.QA,
                update_access=[CapabilityAccessPatch(
                    capability_id=cap_id,
                    access_to=["payment"],
                )],
            )],
            user,
            "access-patch-key-1",
        )

    assert response.status == "pending"
    assert response.message == "App update request accepted"

    with Session(db_engine.engine) as session:
        # orders-api lost its edge; payment gained the only one.
        accesses = session.exec(select(CapabilityAccess)).all()
        assert {(a.capabilityId, a.serviceId) for a in accesses} == {
            (cap_id, 2),
        }

        cap = session.get(Capability, cap_id)
        assert cap.status == CapabilityStatus.PENDING
        assert cap.errorMessage is None
        assert cap.modifiedBy == "owner@makeway.io"

        request = session.get(Request, response.request_id)
        assert request.requestType == RequestType.UPDATE_APP
        assert request.rawRequest["updates"][0]["update_access"] == [
            {"capability_id": cap_id, "access_to": ["payment"]}
        ]

        job = session.get(Job, response.job_id)
        assert job.status == JobStatus.PENDING

    assert queue.published == [
        {"request_id": response.request_id, "job_id": response.job_id}
    ]


def test_access_patch_negative_paths() -> None:
    app_id, _svc, cap_id, _user_id = _seed_created_app()

    # A prod cluster + two prod services + a capability bound only to prod,
    # so env-scoping and prod-shrink paths can be exercised.
    with Session(db_engine.engine) as session:
        cluster = Cluster(
            clusterName="prod-cluster",
            kubeApiEndpoint="https://k8s.prod",
            kubeToken="prod-token",
            kubeCaCert="prod-ca",
            environment="prod",
        )
        session.add(cluster)
        session.flush()
        for name in ("payment-prod", "billing-prod"):
            session.add(
                Service(
                    svcName=f"{name}",
                    serviceType=ServiceType.NODE_JS,
                    clusterId=cluster.clusterId,
                    appId=app_id,
                )
            )
        session.flush()
        prod_svc = session.exec(
            select(Service).where(Service.svcName == "payment-prod")
        ).first()
        prod_cap = Capability(
            capabilityType="storage", status=CapabilityStatus.PENDING
        )
        session.add(prod_cap)
        session.flush()
        session.add(
            CapabilityAccess(capabilityId=prod_cap.capabilityId, serviceId=prod_svc.svcId)
        )
        session.commit()
        prod_cap_id = prod_cap.capabilityId

    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        # Unknown capability id -> 404.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, update_access=[
                    CapabilityAccessPatch(capability_id=9999, access_to=["orders-api"]),
                ])],
                user,
                "patch-ghost-key-1",
            )
            raise AssertionError("unknown capability id should raise")
        except NotFoundException:
            pass

        # A qa capability patched from a prod delta is out of scope -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.PROD, update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=["payment"]),
                ])],
                user,
                "patch-scope-key-2",
            )
            raise AssertionError("cross-env patch should raise")
        except InvalidRequestException as exc:
            assert "does not belong to this app" in exc.message

        # Empty replacement list -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=[]),
                ])],
                user,
                "patch-empty-key-3",
            )
            raise AssertionError("empty access_to should raise")
        except InvalidRequestException as exc:
            assert "must not be empty" in exc.message

        # Patch colliding with a capability removal -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, remove_capabilities=["rel_database"],
                           update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=["orders-api"]),
                ])],
                user,
                "patch-remove-key-4",
            )
            raise AssertionError("patch+remove should raise")
        except InvalidRequestException as exc:
            assert "access-patched and removed" in exc.message

        # Patch colliding with a re-declared capability -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, capabilities=[CapabilityDto(
                    config=DatabaseConfig(name="orders", capacity=2),
                    access_to=["orders-api"],
                )], update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=["orders-api"]),
                ])],
                user,
                "patch-redeclare-key-5",
            )
            raise AssertionError("patch+redeclare should raise")
        except InvalidRequestException as exc:
            assert "access-patched and re-declared" in exc.message

        # Granting access to a removed service -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, remove_services=["orders-api"],
                           update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=["orders-api"]),
                ])],
                user,
                "patch-grant-key-6",
            )
            raise AssertionError("grant to removed service should raise")
        except InvalidRequestException as exc:
            assert "orders-api" in exc.message

        # Unknown service in the replacement list -> 400.
        try:
            service.submit(
                "order-service",
                [EnvConfig(env=Environment.QA, update_access=[
                    CapabilityAccessPatch(capability_id=cap_id, access_to=["ghost"]),
                ])],
                user,
                "patch-unknown-svc-key-7",
            )
            raise AssertionError("unknown access_to service should raise")
        except InvalidRequestException as exc:
            assert "ghost" in exc.message

        # Prod shrink without confirm -> 400; with confirm -> accepted.
        shrink = [EnvConfig(env=Environment.PROD, update_access=[
            CapabilityAccessPatch(capability_id=prod_cap_id, access_to=["billing"]),
        ])]
        try:
            service.submit("order-service", shrink, user, "patch-prod-key-8")
            raise AssertionError("prod shrink without confirm should raise")
        except InvalidRequestException as exc:
            assert "confirm=true" in exc.message

        response = service.submit(
            "order-service", shrink, user, "patch-prod-key-9", confirm=True
        )
        assert response.status == "pending"

    assert queue.published == [
        {"request_id": response.request_id, "job_id": response.job_id}
    ]

    # The confirmed patch swapped payment-prod's edge for billing-prod's.
    with Session(db_engine.engine) as session:
        prod_accesses = session.exec(
            select(CapabilityAccess).where(
                CapabilityAccess.capabilityId == prod_cap_id
            )
        ).all()
        assert len(prod_accesses) == 1
        svc = session.get(Service, prod_accesses[0].serviceId)
        assert svc.svcName == "billing-prod"


def test_capability_access_scopes_to_own_app_on_name_collision() -> None:
    """Two apps each running an identically-named service (svcName is unique
    only WITHIN an app): a capability added to the second app must bind to the
    second app's service row, never the first app's. An edge on the wrong
    app's row makes the capability invisible to its own portal page and to
    the infra-provisioning worker, which both derive through access edges."""
    _seed_created_app()  # app "order-service" with its orders-api-qa row

    # A second app in the same team, with its OWN orders-api-qa row.
    with Session(db_engine.engine) as session:
        team = session.exec(select(Team)).first()
        cluster = session.exec(
            select(Cluster).where(Cluster.environment == "qa")
        ).first()
        app2 = App(appName="billing-service", teamId=team.teamId)
        session.add(app2)
        session.flush()
        svc2 = Service(
            svcName="orders-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster.clusterId,
            appId=app2.appId,
        )
        session.add(svc2)
        session.commit()
        app2_id, svc2_id = app2.appId, svc2.svcId

    # Repository level: the app-scoped lookup resolves the right row.
    with Session(db_engine.engine) as session:
        repo = ServiceRepository(session)
        assert repo.get_by_name("orders-api-qa", app_id=app2_id).svcId == svc2_id

    # Service level: add a rel_database capability to the SECOND app, granting
    # access to "orders-api" — the colliding name.
    queue = _RecordingQueue()
    with Session(db_engine.engine) as session:
        service = _build_service(session, queue)
        user = session.exec(select(User)).first()

        response = service.submit(
            app_name="billing-service",
            updates=_db_update(),
            user=user,
            idempotency_key="collision-key-1",
        )

    assert response.status == "pending"

    with Session(db_engine.engine) as session:
        # The new edge points at the second app's row, not the first app's.
        accesses = session.exec(select(CapabilityAccess)).all()
        new_edges = [a for a in accesses if a.capabilityId != 1]
        assert len(new_edges) == 1
        assert new_edges[0].serviceId == svc2_id

        request = session.get(Request, response.request_id)
        assert request.appId == app2_id


def _reset_db() -> None:
    """Fresh database per test (unique keys collide on a shared file)."""
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_update_grows_database_and_adds_messaging()
    print("test_update_grows_database_and_adds_messaging .... OK")

    _reset_db()
    test_update_adds_service_and_grants_access()
    print("test_update_adds_service_and_grants_access .... OK")

    _reset_db()
    test_idempotent_replay_returns_original_request()
    print("test_idempotent_replay_returns_original_request .... OK")

    _reset_db()
    test_rejected_while_request_in_flight()
    print("test_rejected_while_request_in_flight .... OK")

    _reset_db()
    test_negative_paths()
    print("test_negative_paths .... OK")

    _reset_db()
    test_update_removes_capability_and_purges_on_success()
    print("test_update_removes_capability_and_purges_on_success .... OK")

    _reset_db()
    test_update_removes_service_and_capability_together()
    print("test_update_removes_service_and_capability_together .... OK")

    _reset_db()
    test_orphaned_capability_rejects_service_removal()
    print("test_orphaned_capability_rejects_service_removal .... OK")

    _reset_db()
    test_update_removal_negative_paths()
    print("test_update_removal_negative_paths .... OK")

    _reset_db()
    test_prod_removal_requires_confirm()
    print("test_prod_removal_requires_confirm .... OK")

    _reset_db()
    test_access_patch_replaces_bindings()
    print("test_access_patch_replaces_bindings .... OK")

    _reset_db()
    test_access_patch_negative_paths()
    print("test_access_patch_negative_paths .... OK")

    _reset_db()
    test_capability_access_scopes_to_own_app_on_name_collision()
    print("test_capability_access_scopes_to_own_app_on_name_collision .... OK")

    print("All AppUpdateService tests passed.")