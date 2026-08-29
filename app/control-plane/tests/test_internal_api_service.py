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
# register on SQLModel.metadata (import order bug from earlier attempts).
from sqlmodel import SQLModel, Session, select  # noqa: E402

import database.db_engine as db_engine  # noqa: E402
from database.models.app import App  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
from database.models.job import Job  # noqa: E402
from database.models.request import Request  # noqa: E402
from database.models.service import Service  # noqa: E402
from dto.enums.job_step import JobStep  # noqa: E402
from dto.enums.job_status import JobStatus  # noqa: E402
from dto.enums.request_status import RequestStatus  # noqa: E402
from dto.enums.request_type import RequestType  # noqa: E402
from dto.enums.service_type import ServiceType  # noqa: E402
from dto.request.internal import InternalStatusUpdateRequest  # noqa: E402
from exceptions.base import BadRequestException, NotFoundException  # noqa: E402
from repository.app_repository import AppRepository  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
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
    )


def _seed() -> tuple[int, int, int, int]:
    """cluster + app + two services (dev/qa) + request + job; returns ids."""
    with Session(db_engine.engine) as session:
        cluster = Cluster(
            clusterName="dev-cluster",
            kubeApiEndpoint="https://k8s.dev",
            environment="dev",
        )
        session.add(cluster)
        session.flush()

        app = App(appName="order-service", teamId=1)
        session.add(app)
        session.flush()

        svc_dev = Service(
            svcName="orders-api-dev",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster.clusterId,
            appId=app.appId,
        )
        svc_qa = Service(
            svcName="orders-api-qa",
            serviceType=ServiceType.FAST_API,
            clusterId=cluster.clusterId,
            appId=app.appId,
        )
        session.add(svc_dev)
        session.add(svc_qa)
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
        return req.requestId, job.jobId, svc_dev.svcId, svc_qa.svcId


def test_details_and_status_callbacks() -> None:
    request_id, job_id, svc_dev_id, svc_qa_id = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)
        details = api.get_request_details(request_id)

        assert details["app"]["appName"] == "order-service"
        assert [s["svcName"] for s in details["services"]] == ["orders-api-dev", "orders-api-qa"]
        assert all(s["serviceType"] == "fast-api" for s in details["services"])
        assert details["environments"] == ["dev"]
        assert details["job"]["jobId"] == job_id
        assert details["job"]["status"] == "pending"

        # In-progress callback with the execution ARN.
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(
                jobId=job_id,
                step="create_project",
                status="in_progress",
                executionArn="arn:aws:states:ap-south-1:111:execution:x:y",
            ),
        )
        # Success callback with the repo URLs and per-service folder paths.
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(
                jobId=job_id,
                step="create_project",
                status="success",
                appRepoUrl="https://github.com/kapil4457/order-service",
                gitOpsRepoUrl="https://github.com/kapil4457/makeway",
                serviceRepoPaths=[
                    {"svcId": svc_dev_id, "repoPath": "orders-api"},
                    {"svcId": svc_qa_id, "repoPath": "orders-api"},
                ],
            ),
        )

    with Session(db_engine.engine) as session:
        app = session.get(App, 1)
        job = session.get(Job, job_id)
        req = session.get(Request, request_id)
        services = session.exec(select(Service).order_by(Service.svcId)).all()

        assert app.appRepoUrl == "https://github.com/kapil4457/order-service"
        assert app.gitOpsRepoUrl == "https://github.com/kapil4457/makeway"
        assert job.status == JobStatus.SUCCESS
        assert job.step == JobStep.CREATE_PROJECT
        assert job.stepFunctionExecutionArn == "arn:aws:states:ap-south-1:111:execution:x:y"
        assert job.errorDetail is None
        assert req.requestStatus == RequestStatus.SUCCESS
        assert {(s.svcName, s.repoPath) for s in services} == {
            ("orders-api-dev", "orders-api"),
            ("orders-api-qa", "orders-api"),
        }


def test_failure_rolls_up_request_and_records_error() -> None:
    request_id, job_id, _, _ = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(jobId=job_id, status="failed", error="boom"),
        )

    with Session(db_engine.engine) as session:
        assert session.get(Request, request_id).requestStatus == RequestStatus.FAILED
        assert session.get(Job, job_id).errorDetail == "boom"


def test_negative_paths() -> None:
    request_id, job_id, _, _ = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)

        # Missing request -> 404.
        try:
            api.update_request_status(999999, InternalStatusUpdateRequest(status="success"))
            raise AssertionError("missing request should raise NotFoundException")
        except NotFoundException:
            pass

        # Bogus status -> 400.
        try:
            api.update_request_status(
                request_id,
                InternalStatusUpdateRequest(jobId=job_id, status="bogus"),
            )
            raise AssertionError("bogus status should raise BadRequestException")
        except BadRequestException:
            pass

        # Bogus step -> 400.
        try:
            api.update_request_status(
                request_id,
                InternalStatusUpdateRequest(jobId=job_id, status="success", step="nope"),
            )
            raise AssertionError("bogus step should raise BadRequestException")
        except BadRequestException:
            pass

        # Unknown service id in repo paths -> 404.
        try:
            api.update_request_status(
                request_id,
                InternalStatusUpdateRequest(
                    jobId=job_id,
                    status="success",
                    serviceRepoPaths=[{"svcId": 999999, "repoPath": "x"}],
                ),
            )
            raise AssertionError("unknown service should raise NotFoundException")
        except NotFoundException:
            pass

        # Callback without a jobId falls back to the latest job on the request.
        result = api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(status="success"),
        )
        assert result["jobId"] == job_id


def _reset_db() -> None:
    """Drop and recreate every table so each test starts from a clean DB.

    The generic App/Request rows (_seed) hit UNIQUE constraints (appName,
    idempotencyKey, cluster.clusterName) if the SQLite file is shared across
    tests, so each test gets a fresh database.
    """
    SQLModel.metadata.drop_all(db_engine.engine)
    SQLModel.metadata.create_all(db_engine.engine)


if __name__ == "__main__":
    _reset_db()
    test_details_and_status_callbacks()
    print("test_details_and_status_callbacks .... OK")

    _reset_db()
    test_failure_rolls_up_request_and_records_error()
    print("test_failure_rolls_up_request_and_records_error .... OK")

    _reset_db()
    test_negative_paths()
    print("test_negative_paths .... OK")

    print("All InternalApiService tests passed.")