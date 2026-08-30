"""Regression for the deploy-reporter contract: ``DeploymentSetup`` upsert.

Exercises ``InternalApiService.record_deployment_setup`` the way the
(ArgoCD/rollout) reporter calls it — including idempotent retries and negative
paths — using the same direct-run pattern as ``test_internal_api_service.py``:
```
python tests/test_deployment_setup_reporter.py
```
(drop_all/create_all + model registration live in this file; run it directly,
not via pytest, so the host ``__main__`` at the bottom recreates the schema.)
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
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
# register on SQLModel.metadata (import order bug from earlier attempts).
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
from dto.enums.capability_status import CapabilityStatus  # noqa: E402
from dto.enums.job_step import JobStep  # noqa: E402
from dto.enums.job_status import JobStatus  # noqa: E402
from dto.enums.request_status import RequestStatus  # noqa: E402
from dto.enums.request_type import RequestType  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from dto.request.internal import InternalDeploymentSetupReport  # noqa: E402
from exceptions.base import NotFoundException  # noqa: E402
from repository.app_repository import AppRepository  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
from repository.deployment_setup_repository import DeploymentSetupRepository  # noqa: E402
from repository.job_repository import JobRepository  # noqa: E402
from repository.request_repository import RequestRepository  # noqa: E402
from repository.service_repository import ServiceRepository  # noqa: E402
from service.internal_api_service import InternalApiService  # noqa: E402


def _build_service(session: Session) -> InternalApiService:
    return InternalApiService(
        session=session,
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
        appRepository=AppRepository(session),
        serviceRepository=ServiceRepository(session),
        clusterRepository=ClusterRepository(session),
        capabilityRepository=None,  # not needed by the reporter endpoints
        capabilityAccessRepository=None,  # not needed by the reporter endpoints
        infraRequirementRepository=None,  # not needed by the reporter endpoints
        deploymentSetupRepository=DeploymentSetupRepository(session),
    )


def _seed() -> tuple[int, int, int, int, int, int]:
    """clusters + app + two services (qa/uat) + request + job.

    Returns (request_id, job_id, svc_qa_id, svc_uat_id, cap_id, infra_id).
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

        app = App(appName="order-service", teamId=1)
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

        cap = Capability(capabilityType="rel_database", status=CapabilityStatus.PENDING)
        session.add(cap)
        session.flush()

        cap_access = CapabilityAccess(capabilityId=cap.capabilityId, serviceId=svc_qa.svcId)
        session.add(cap_access)
        session.flush()

        infra = InfraRequirement(
            capabilityId=cap.capabilityId,
            config={"type": "rel_database", "name": "orders", "capacity": 5},
        )
        session.add(infra)
        session.flush()

        req = Request(
            idempotencyKey="key-123",
            requestType=RequestType.CREATE_APP,
            requestStatus=RequestStatus.PENDING,
            appId=app.appId,
            rawRequest={"app_name": "order-service"},
        )
        session.add(req)
        session.flush()

        job = Job(requestId=req.requestId, step=JobStep.CREATE_PROJECT, status=JobStatus.PENDING)
        session.add(job)
        session.flush()

        session.commit()
        return (
            req.requestId,
            job.jobId,
            svc_qa.svcId,
            svc_uat.svcId,
            cap.capabilityId,
            infra.infraRequirementId,
        )


def test_report_creates_deployment_setup() -> None:
    _, _, svc_id, _, _, _ = _seed()

    report = InternalDeploymentSetupReport(
        svcId=svc_id,
        status="synced",
        argocdAppName="orders-api-qa",
        lastSyncedAt=datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
    )

    with Session(db_engine.engine) as session:
        result = _build_service(session).record_deployment_setup(report)

    assert result["message"] == "Deployment setup recorded."
    assert result["svcId"] == svc_id
    assert result["status"] == "synced"

    with Session(db_engine.engine) as session:
        dep = session.exec(
            select(DeploymentSetup)
            .where(DeploymentSetup.serviceId == svc_id)
            .order_by(DeploymentSetup.deploymentSetupId.desc())
        ).first()
        assert dep is not None
        assert dep.serviceId == svc_id
        assert dep.status == "synced"
        assert dep.argocdAppName == "orders-api-qa"
        # SQLite stores datetimes without tzinfo, so the round-tripped value
        # comes back naive (Postgres with timestamptz keeps the offset).
        assert dep.lastSyncedAt == datetime(2026, 8, 30, 12, 0, 0)
        assert dep.errorMessage is None


def test_report_upserts_in_place_on_retry() -> None:
    _, _, svc_id, _, _, _ = _seed()

    first = InternalDeploymentSetupReport(
        svcId=svc_id,
        status="synced",
        argocdAppName="orders-api-qa",
        lastSyncedAt=datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
    )

    with Session(db_engine.engine) as session:
        _build_service(session).record_deployment_setup(first)

    # A later report (e.g. a failed sync) must update the same row, not create
    # a second one — the idempotency seam for reporter retries.
    second = InternalDeploymentSetupReport(
        svcId=svc_id,
        status="failed",
        errorMessage="ArgoCD sync failed: unable to reach image tag",
    )

    with Session(db_engine.engine) as session:
        _build_service(session).record_deployment_setup(second)

    with Session(db_engine.engine) as session:
        deps = session.exec(select(DeploymentSetup)).all()
        assert len(deps) == 1
        dep = deps[0]
        assert dep.status == "failed"
        assert dep.errorMessage == "ArgoCD sync failed: unable to reach image tag"
        # Fields from the prior report the new one didn't include are kept.
        assert dep.argocdAppName == "orders-api-qa"


def test_group_lists_env_services() -> None:
    _, _, svc_qa_id, svc_uat_id, _, _ = _seed()

    with Session(db_engine.engine) as session:
        result = _build_service(session).list_deployment_group_services(
            "order-service", "qa"
        )
        assert result["env"] == "qa"
        assert result["svcIds"] == [svc_qa_id]

    with Session(db_engine.engine) as session:
        result = _build_service(session).list_deployment_group_services(
            "order-service", "uat"
        )
        assert result["env"] == "uat"
        assert result["svcIds"] == [svc_uat_id]

    # Env with no cluster yet -> honest empty group (reporter skips it).
    with Session(db_engine.engine) as session:
        result = _build_service(session).list_deployment_group_services(
            "order-service", "prod"
        )
        assert result["env"] == "prod"
        assert result["svcIds"] == []


def test_group_rejects_missing_app() -> None:
    with Session(db_engine.engine) as session:
        try:
            _build_service(session).list_deployment_group_services(
                "does-not-exist", "qa"
            )
            raise AssertionError("missing app should raise NotFoundException")
        except NotFoundException as exc:
            assert exc.error_code == "APP_NOT_FOUND"


def test_report_rejects_missing_service() -> None:
    with Session(db_engine.engine) as session:
        try:
            _build_service(session).record_deployment_setup(
                InternalDeploymentSetupReport(svcId=999999, status="synced")
            )
            raise AssertionError("missing service should raise NotFoundException")
        except NotFoundException as exc:
            assert exc.error_code == "SERVICE_NOT_FOUND"


def _reset_db() -> None:
    """Drop and recreate every table so each test starts from a clean DB."""
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_report_creates_deployment_setup()
    print("test_report_creates_deployment_setup .... OK")

    _reset_db()
    test_report_upserts_in_place_on_retry()
    print("test_report_upserts_in_place_on_retry .... OK")

    _reset_db()
    test_group_lists_env_services()
    print("test_group_lists_env_services .... OK")

    _reset_db()
    test_group_rejects_missing_app()
    print("test_group_rejects_missing_app .... OK")

    _reset_db()
    test_report_rejects_missing_service()
    print("test_report_rejects_missing_service .... OK")

    print("All deployment-setup reporter regression tests passed.")