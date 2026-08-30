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
from database.models.capability import Capability  # noqa: E402
from database.models.capability_access import CapabilityAccess  # noqa: E402
from database.models.cluster import Cluster  # noqa: E402
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
from dto.request.internal import InternalStatusUpdateRequest  # noqa: E402
from exceptions.base import BadRequestException, NotFoundException  # noqa: E402
from repository.app_repository import AppRepository  # noqa: E402
from repository.capability_access_repository import CapabilityAccessRepository  # noqa: E402
from repository.capability_repository import CapabilityRepository  # noqa: E402
from repository.cluster_repository import ClusterRepository  # noqa: E402
from repository.deployment_setup_repository import DeploymentSetupRepository  # noqa: E402
from repository.infra_requirement_repository import InfraRequirementRepository  # noqa: E402
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
        capabilityRepository=CapabilityRepository(session),
        capabilityAccessRepository=CapabilityAccessRepository(session),
        infraRequirementRepository=InfraRequirementRepository(session),
        deploymentSetupRepository=DeploymentSetupRepository(session),
    )


def _seed() -> tuple[int, int, int, int, int, int]:
    """clusters + app + two services (qa/uat) + capability + request + job.

    Returns (request_id, job_id, svc_qa_id, svc_uat_id, capability_id,
    infra_requirement_id).
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

        cap = Capability(
            capabilityType="rel_database",
            status=CapabilityStatus.PENDING,
        )
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


def test_details_and_status_callbacks() -> None:
    request_id, job_id, svc_qa_id, svc_uat_id, cap_id, _infra_id = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)
        details = api.get_request_details(request_id)

        assert details["app"]["appName"] == "order-service"
        assert [s["svcName"] for s in details["services"]] == ["orders-api-qa", "orders-api-uat"]
        assert all(s["serviceType"] == "fast-api" for s in details["services"])
        assert details["environments"] == ["qa", "uat"]
        assert details["job"]["jobId"] == job_id
        assert details["job"]["status"] == "pending"

        # Provision-infra worker gets each capability's config + target namespace.
        caps = details["capabilities"]
        assert [c["capabilityType"] for c in caps] == ["rel_database"]
        assert caps[0]["capabilityId"] == cap_id
        assert caps[0]["config"]["name"] == "orders"
        assert caps[0]["environment"] == "qa"
        assert caps[0]["namespace"] == "order-service-qa"
        assert caps[0]["accessToServices"] == ["orders-api-qa"]

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
                gitOpsPath="argocd/apps/order-service/",
                serviceRepoPaths=[
                    {"svcId": svc_qa_id, "repoPath": "orders-api"},
                    {"svcId": svc_uat_id, "repoPath": "orders-api"},
                ],
            ),
        )

    with Session(db_engine.engine) as session:
        app = session.get(App, 1)
        job = session.get(Job, job_id)
        req = session.get(Request, request_id)
        services = session.exec(select(Service).order_by(Service.svcId)).all()

        assert app.appRepoUrl == "https://github.com/kapil4457/order-service"
        assert app.gitOpsPath == "argocd/apps/order-service/"
        assert job.status == JobStatus.SUCCESS
        assert job.step == JobStep.CREATE_PROJECT
        assert job.stepFunctionExecutionArn == "arn:aws:states:ap-south-1:111:execution:x:y"
        assert job.errorDetail is None
        assert req.requestStatus == RequestStatus.SUCCESS
        assert {(s.svcName, s.repoPath) for s in services} == {
            ("orders-api-qa", "orders-api"),
            ("orders-api-uat", "orders-api"),
        }


def test_failure_rolls_up_request_and_records_error() -> None:
    request_id, job_id, _, _, _, _ = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(jobId=job_id, status="failed", error="boom"),
        )

    with Session(db_engine.engine) as session:
        assert session.get(Request, request_id).requestStatus == RequestStatus.FAILED
        assert session.get(Job, job_id).errorDetail == "boom"


def test_capability_outputs_written_from_step2_callback() -> None:
    request_id, job_id, _svc_qa, _svc_uat, capability_id, infra_id = _seed()

    with Session(db_engine.engine) as session:
        api = _build_service(session)
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(
                jobId=job_id,
                step="provision_infra",
                status="in_progress",
            ),
        )
        # Step-2 extract Lambda reports each capability's connection details
        # (outputRef = runtime metadata, secretRef = the Secrets Manager ARN).
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(
                jobId=job_id,
                step="provision_infra",
                status="success",
                capabilities=[
                    {
                        "capabilityId": capability_id,
                        "status": "success",
                        "outputRef": {
                            "endpoint": "orders-db.xxxxxxxxxxxx.ap-south-1.rds.amazonaws.com",
                            "port": 5432,
                            "databaseName": "orders",
                        },
                        "secretRef": "arn:aws:secretsmanager:ap-south-1:111:secret:makeway/order-service/qa/orders-abc",
                    }
                ],
            ),
        )

    with Session(db_engine.engine) as session:
        infra = session.get(InfraRequirement, infra_id)
        assert infra.outputRef["databaseName"] == "orders"
        assert infra.outputRef["port"] == 5432
        assert infra.secretRef.endswith("makeway/order-service/qa/orders-abc")
        assert infra.errorMessage is None
        assert infra.modifiedBy == "makeway-worker"

        cap = session.get(Capability, capability_id)
        assert cap.status == CapabilityStatus.SUCCESS
        assert cap.modifiedBy == "makeway-worker"

        # Partially-failed report records the error but still persists.
        session.expire_all()
        api = _build_service(session)
        api.update_request_status(
            request_id,
            InternalStatusUpdateRequest(
                jobId=job_id,
                step="provision_infra",
                status="failed",
                capabilities=[
                    {
                        "capabilityId": capability_id,
                        "status": "partially_failed",
                        "errorMessage": "rds create failed: timeout",
                    }
                ],
            ),
        )

    with Session(db_engine.engine) as session:
        cap = session.get(Capability, capability_id)
        assert cap.status == CapabilityStatus.PARTIALLY_FAILED
        assert cap.errorMessage == "rds create failed: timeout"
        infra = session.get(InfraRequirement, infra_id)
        assert infra.errorMessage == "rds create failed: timeout"


def test_negative_paths() -> None:
    request_id, job_id, _, _, _, _ = _seed()

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

        # Capability reported by the worker that doesn't belong to this app -> 400.
        cap = Capability(capabilityType="rel_database", status=CapabilityStatus.PENDING)
        session.add(cap)
        session.flush()
        try:
            api.update_request_status(
                request_id,
                InternalStatusUpdateRequest(
                    jobId=job_id,
                    status="success",
                    capabilities=[{"capabilityId": cap.capabilityId, "status": "success"}],
                ),
            )
            raise AssertionError("foreign capability should raise BadRequestException")
        except BadRequestException as exc:
            assert exc.error_code == "CAPABILITY_NOT_IN_APP"


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
    test_capability_outputs_written_from_step2_callback()
    print("test_capability_outputs_written_from_step2_callback .... OK")

    _reset_db()
    test_negative_paths()
    print("test_negative_paths .... OK")

    print("All InternalApiService tests passed.")