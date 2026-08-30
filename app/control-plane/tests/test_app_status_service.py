"""Regression tests for the app-status aggregation (``AppStatusService``).

Run directly — not under pytest — so the ``drop_all`` / ``create_all`` below
can prepare a fresh sqlite database, same pattern as
``tests/test_internal_api_service.py``.
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


# Import every model before create_all so tables register on metadata.
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
from dto.enums.job_step import JobStep  # noqa: E402
from dto.enums.job_status import JobStatus  # noqa: E402
from dto.enums.request_status import RequestStatus  # noqa: E402
from dto.enums.request_type import RequestType  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from exceptions.base import ForbiddenException, NotFoundException  # noqa: E402
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
from service.app_status_service import AppStatusService  # noqa: E402


def _build_status_service(session: Session) -> AppStatusService:
    return AppStatusService(
        session=session,
        appRepository=AppRepository(session),
        teamMemberRepository=TeamMemberRepository(session),
        clusterRepository=ClusterRepository(session),
        serviceRepository=ServiceRepository(session),
        capabilityRepository=CapabilityRepository(session),
        capabilityAccessRepository=CapabilityAccessRepository(session),
        infraRequirementRepository=InfraRequirementRepository(session),
        deploymentSetupRepository=DeploymentSetupRepository(session),
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
    )


# ------------------------------------------------------------------ #
# Seeding
# ------------------------------------------------------------------ #

def _seed_user(session: Session, email: str) -> User:
    user = User(email=email, passwordHash="hash")
    session.add(user)
    session.flush()
    return user


def _seed_team(session: Session, team_name: str, user: User) -> Team:
    team = Team(teamName=team_name)
    session.add(team)
    session.flush()
    member = TeamMember(teamId=team.teamId, userId=user.userId)
    session.add(member)
    session.flush()
    return team


def _seed() -> tuple:
    """Clusters + team + owner + outsider + app + two services (qa/uat) +
    capability + deployment + request + job.

    Returns (owner, outsider, team, app, svc_qa_id, svc_uat_id, cap_id).
    """
    with Session(db_engine.engine) as session:
        cluster_qa = Cluster(
            clusterName="qa-cluster",
            kubeApiEndpoint="https://k8s.qa",
            environment="qa",
        )
        cluster_uat = Cluster(
            clusterName="uat-cluster",
            kubeApiEndpoint="https://k8s.uat",
            environment="uat",
        )
        session.add(cluster_qa)
        session.add(cluster_uat)
        session.flush()

        owner = _seed_user(session, "owner@makeway.dev")
        outsider = _seed_user(session, "outsider@makeway.dev")
        team = _seed_team(session, "orders-team", owner)

        app = App(appName="order-service", teamId=team.teamId, createdBy=owner.email)
        session.add(app)
        session.flush()

        svc_qa = Service(
            svcName="orders-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster_qa.clusterId,
            appId=app.appId,
        )
        svc_uat = Service(
            svcName="orders-api-uat",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster_uat.clusterId,
            appId=app.appId,
        )
        session.add(svc_qa)
        session.add(svc_uat)
        session.flush()

        dep = DeploymentSetup(
            serviceId=svc_qa.svcId,
            status="success",
            argocdAppName="orders-api-qa",
            errorMessage=None,
        )
        session.add(dep)
        session.flush()

        cap = Capability(
            capabilityType="rel_database",
            status=CapabilityStatus.SUCCESS,
        )
        session.add(cap)
        session.flush()

        cap_access = CapabilityAccess(capabilityId=cap.capabilityId, serviceId=svc_qa.svcId)
        session.add(cap_access)
        session.flush()

        infra = InfraRequirement(
            capabilityId=cap.capabilityId,
            config={"type": "rel_database", "name": "orders", "capacity": 5},
            outputRef={"endpoint": "orders.internal", "port": 5432},
            secretRef="arn:aws:secretsmanager:ap-south-1:111:secret:orders-qa",
        )
        session.add(infra)
        session.flush()

        req = Request(
            idempotencyKey="key-status-123",
            requestType=RequestType.CREATE_APP,
            requestStatus=RequestStatus.SUCCESS,
            appId=app.appId,
            rawRequest={"app_name": "order-service"},
        )
        session.add(req)
        session.flush()

        job = Job(requestId=req.requestId, step=JobStep.ARGOCD_SETUP, status=JobStatus.SUCCESS)
        session.add(job)
        session.flush()

        session.commit()
        return (
            owner.userId,
            outsider.userId,
            team.teamId,
            app.appId,
            svc_qa.svcId,
            svc_uat.svcId,
            cap.capabilityId,
        )


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #

def test_app_status_aggregates_per_env_with_health_and_errors() -> None:
    owner_id, _outsider_id, _team_id, _app_id, svc_qa_id, svc_uat_id, cap_id = _seed()

    with Session(db_engine.engine) as session:
        owner = session.get(User, owner_id)
        status = _build_status_service(session).get_app_status(
            app_name="order-service",
            current_user=owner,
        )

    assert status.appName == "order-service"
    assert status.teamName == "orders-team"
    assert status.request is not None
    assert status.request.requestStatus == "success"
    assert status.request.jobStep == "argocd_setup"
    assert status.request.jobStatus == "success"

    envs = {env.env: env for env in status.envStatuses}
    assert set(envs) == {"qa", "uat"}

    qa = envs["qa"]
    assert qa.cluster.clusterName == "qa-cluster"
    assert [s.svcName for s in qa.services] == ["orders-api-qa"]
    # Persisted rollout state drives a real (non-unknown) health value.
    assert qa.services[0].svcId == svc_qa_id
    assert qa.services[0].health.value == "healthy"
    assert qa.services[0].healthSource == "persisted"
    assert qa.services[0].deployment.argocdAppName == "orders-api-qa"
    assert qa.services[0].error is None

    assert [c.capabilityId for c in qa.capabilities] == [cap_id]
    assert qa.capabilities[0].name == "orders"
    assert qa.capabilities[0].status == "success"
    assert qa.capabilities[0].infra.outputRef == {"endpoint": "orders.internal", "port": 5432}
    assert qa.capabilities[0].infra.secretRef.startswith("arn:aws:secretsmanager")

    # Connectivity: the qa service is bound to the capability.
    assert qa.connectivity[0].serviceSvcId == svc_qa_id
    assert qa.connectivity[0].capabilityId == cap_id
    assert qa.connectivity[0].accessConfigured is True
    assert qa.connectivity[0].status.value == "configured"
    assert qa.connectivity[0].source == "persisted"
    assert qa.errors == []

    uat = envs["uat"]
    assert [s.svcName for s in uat.services] == ["orders-api-uat"]
    # No deployment recorded for uat -> honest unknown + no deployment block.
    assert uat.services[0].svcId == svc_uat_id
    assert uat.services[0].health.value == "unknown"
    assert uat.services[0].deployment is None
    assert uat.services[0].error is None
    # Capabilities are env-scoped through their access edges: none in uat.
    assert uat.capabilities == []
    assert uat.connectivity == []
    assert uat.errors == []


def test_failed_deployment_and_capability_surface_errors() -> None:
    owner_id, _outsider_id, _team_id, _app_id, svc_qa_id, _svc_uat_id, cap_id = _seed()

    # Mark the deployment failed and the capability failed to observe both
    # error paths in the aggregate response.
    with Session(db_engine.engine) as session:
        dep = session.exec(
            select(DeploymentSetup).where(DeploymentSetup.serviceId == svc_qa_id)
        ).first()
        assert dep is not None
        dep.status = "failed"
        dep.errorMessage = "ArgoCD sync failed: unable to reach image tag"
        session.add(dep)

        cap = session.get(Capability, cap_id)
        cap.status = CapabilityStatus.FAILED
        cap.errorMessage = "RDS instance failed to enter ready state"
        session.add(cap)
        session.commit()

    with Session(db_engine.engine) as session:
        owner = session.get(User, owner_id)
        status = _build_status_service(session).get_app_status(
            app_name="order-service",
            current_user=owner,
        )

    qa = next(env for env in status.envStatuses if env.env == "qa")
    assert qa.services[0].health.value == "unhealthy"
    assert qa.services[0].error == "ArgoCD sync failed: unable to reach image tag"
    assert qa.capabilities[0].status == "failed"
    assert "RDS instance failed to enter ready state" in qa.capabilities[0].error

    # Both errors bubble into the env-level errors list.
    assert any("ArgoCD sync failed" in e for e in qa.errors)
    assert any("RDS instance" in e for e in qa.errors)


def test_non_owner_is_forbidden_and_missing_app_is_404() -> None:
    owner_id, outsider_id, _team_id, _app_id, _s, _u, _c = _seed()

    with Session(db_engine.engine) as session:
        svc = _build_status_service(session)
        outsider = session.get(User, outsider_id)
        owner = session.get(User, owner_id)

        # A member of a different team cannot read the app's status.
        try:
            svc.get_app_status(app_name="order-service", current_user=outsider)
            raise AssertionError("expected ForbiddenException for a non-owner")
        except ForbiddenException as exc:
            assert exc.error_code == "APP_ACCESS_FORBIDDEN"

        # An unknown app 404s first, before any authorization check.
        try:
            svc.get_app_status(app_name="does-not-exist", current_user=owner)
            raise AssertionError("expected NotFoundException for a missing app")
        except NotFoundException as exc:
            assert exc.error_code == "APP_NOT_FOUND"


def test_no_request_yet_still_returns_env_layout() -> None:
    # Seed a bare app with one service but no request/job rows (i.e. the
    # request was never created — the reconcile simply hasn't started).
    with Session(db_engine.engine) as session:
        cluster = Cluster(
            clusterName="fresh-cluster",
            kubeApiEndpoint="https://k8s.fresh",
            environment="qa",
        )
        session.add(cluster)
        session.flush()

        owner = _seed_user(session, "fresh@makeway.dev")
        team = _seed_team(session, "fresh-team", owner)

        app = App(appName="fresh-app", teamId=team.teamId, createdBy=owner.email)
        session.add(app)
        session.flush()

        svc = Service(
            svcName="fresh-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster.clusterId,
            appId=app.appId,
        )
        session.add(svc)
        session.flush()
        session.commit()

        fresh_owner = session.get(User, owner.userId)
        status = _build_status_service(session).get_app_status(
            app_name="fresh-app",
            current_user=fresh_owner,
        )

        assert status.request is None
        assert len(status.envStatuses) == 1
        qa = status.envStatuses[0]
        assert qa.env == "qa"
        assert qa.services[0].svcName == "fresh-api-qa"
        assert qa.services[0].health.value == "unknown"
        assert qa.errors == []


def _reset_db() -> None:
    """Drop and recreate every table so each test starts from a clean DB.

    The seeded rows hit UNIQUE constraints (cluster.clusterName, appName,
    idempotencyKey) if the SQLite file is shared across tests, so each test
    gets a fresh database.
    """
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_app_status_aggregates_per_env_with_health_and_errors()
    print("test_app_status_aggregates_per_env_with_health_and_errors .... OK")

    _reset_db()
    test_failed_deployment_and_capability_surface_errors()
    print("test_failed_deployment_and_capability_surface_errors .... OK")

    _reset_db()
    test_non_owner_is_forbidden_and_missing_app_is_404()
    print("test_non_owner_is_forbidden_and_missing_app_is_404 .... OK")

    _reset_db()
    test_no_request_yet_still_returns_env_layout()
    print("test_no_request_yet_still_returns_env_layout .... OK")

    print("All app-status regression tests passed.")