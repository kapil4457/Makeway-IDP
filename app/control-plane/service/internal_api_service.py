"""Internal API used by state-machine workers to read request state and report
back status/URLs.

These endpoints are callable from the Step Functions Lambda workers only
(verified through the ``X-Internal-API-Key`` header dependency). The public
``/app/*`` routes stay the user-facing surface; this router closes the loop
for the async reconcilers.
"""
from sqlmodel import Session

from core import get_logger
from database.models.app import App
from database.models.job import Job
from database.models.request import Request
from dto.enums.job_status import JobStatus
from dto.enums.job_step import JobStep
from dto.enums.request_status import RequestStatus
from dto.request.internal import InternalStatusUpdateRequest
from exceptions.base import (
    BadRequestException,
    NotFoundException,
)
from repository.app_repository import AppRepository
from repository.cluster_repository import ClusterRepository
from repository.job_repository import JobRepository
from repository.request_repository import RequestRepository
from repository.service_repository import ServiceRepository


logger = get_logger(__name__)

# Which worker step owns each job step value. Not yet used for enforcement —
# reserved so multi-step reconciliation can route callbacks safely.
JOB_STEPS = {step.value for step in JobStep}

_JOB_TO_REQUEST_STATUS = {
    JobStatus.PENDING: RequestStatus.PENDING,
    JobStatus.IN_PROGRESS: RequestStatus.IN_PROGRESS,
    JobStatus.SUCCESS: RequestStatus.SUCCESS,
    JobStatus.FAILED: RequestStatus.FAILED,
}


class InternalApiService:

    def __init__(
        self,
        session: Session,
        requestRepository: RequestRepository,
        jobRepository: JobRepository,
        appRepository: AppRepository,
        serviceRepository: ServiceRepository,
        clusterRepository: ClusterRepository,
    ):
        self.session = session
        self.requestRepository = requestRepository
        self.jobRepository = jobRepository
        self.appRepository = appRepository
        self.serviceRepository = serviceRepository
        self.clusterRepository = clusterRepository

    # ------------------------------------------------------------------ #
    # Read-side: what the state machine needs to execute a step
    # ------------------------------------------------------------------ #

    def get_request_details(self, request_id: int) -> dict:
        """Return the app/services/environments/job payload for a request.

        Shape consumed by the Step-1 Lambda worker:

        ``{app: {appId, appName}, services: [{svcId, svcName, serviceType}],
        environments: [...], job: {jobId, status}}``

        ``environments`` is derived from the distinct ``cluster.environment``
        of the request's services (an ``environment`` table no longer exists —
        the cluster carries the environment). ``serviceType`` is emitted as the
        wire value (``fast-api``, ``node-js``, ``spring-boot``) so workers can
        map it directly to a golden-path template.
        """
        request = self._get_request(request_id)
        app = self._resolve_app(request)

        services = self.serviceRepository.get_by_app(app.appId)

        # Distinct environments across the services' clusters, in first-seen
        # order so the worker's `_strip_env` matches longest suffix first.
        environments: list[str] = []
        seen_cluster_ids = set()
        for svc in services:
            if svc.clusterId in seen_cluster_ids:
                continue
            seen_cluster_ids.add(svc.clusterId)
            cluster = self.clusterRepository.get_by_id(svc.clusterId)
            if cluster is not None and cluster.environment not in environments:
                environments.append(cluster.environment)

        job = self.jobRepository.get_by_request_id(request.requestId)

        return {
            "app": {
                "appId": app.appId,
                "appName": app.appName,
            },
            "services": [
                {
                    "svcId": svc.svcId,
                    "svcName": svc.svcName,
                    "serviceType": svc.serviceType.value,
                }
                for svc in services
            ],
            "environments": environments,
            "job": {
                "jobId": job.jobId if job else None,
                "status": job.status.value if job else None,
            },
        }

    # ------------------------------------------------------------------ #
    # Write-side: status + URL callbacks from workers
    # ------------------------------------------------------------------ #

    def update_request_status(
        self,
        request_id: int,
        payload: InternalStatusUpdateRequest,
    ) -> dict:
        """Apply a worker's status callback.

        Updates the request's job (status/step/ARNS/error), records the app's
        repo URLs and each service's folder path, then rolls the request status
        up from the job status. All writes commit in one unit of work.
        """
        request = self._get_request(request_id)

        status = self._parse_status(payload.status)
        step = self._parse_step(payload.step) if payload.step else None

        job = self._resolve_job(request, payload.jobId)

        job.status = status
        job.modifiedBy = "makeway-worker"
        if step is not None:
            job.step = step
        if payload.executionArn:
            job.stepFunctionExecutionArn = payload.executionArn
        if payload.error is not None:
            job.errorDetail = payload.error

        app = self._resolve_app(request)
        app.modifiedBy = "makeway-worker"
        if payload.appRepoUrl:
            app.appRepoUrl = payload.appRepoUrl
        if payload.gitOpsRepoUrl:
            app.gitOpsRepoUrl = payload.gitOpsRepoUrl

        if payload.serviceRepoPaths:
            for entry in payload.serviceRepoPaths:
                svc = self.serviceRepository.get_by_id(entry.svcId)
                if svc is None:
                    raise NotFoundException(
                        message=f"Service {entry.svcId} not found.",
                        error_code="SERVICE_NOT_FOUND",
                    )
                if entry.repoPath:
                    svc.repoPath = entry.repoPath
                    svc.modifiedBy = "makeway-worker"

        request.requestStatus = _JOB_TO_REQUEST_STATUS[status]
        request.modifiedBy = "makeway-worker"

        self.session.commit()

        logger.info(
            "Request status updated",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "job_id": job.jobId,
                    "status": status.value,
                }
            },
        )

        return {
            "message": "Request status updated.",
            "requestId": request.requestId,
            "jobId": job.jobId,
            "status": status.value,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _get_request(self, request_id: int) -> Request:
        request = self.requestRepository.get_by_id(request_id)
        if request is None:
            raise NotFoundException(
                message=f"Request {request_id} not found.",
                error_code="REQUEST_NOT_FOUND",
            )
        return request

    def _resolve_job(self, request: Request, job_id: int | None) -> Job:
        """The job a callback targets: the reported id, else the latest job
        on the request (workers always send the real id; the fallback keeps
        older callers working)."""
        if job_id:
            job = self.jobRepository.get_by_id(job_id)
            if job is not None:
                return job
        job = self.jobRepository.get_by_request_id(request.requestId)
        if job is None:
            raise NotFoundException(
                message="No job found for this request.",
                error_code="JOB_NOT_FOUND",
            )
        return job

    def _resolve_app(self, request: Request) -> App:
        """The app a request belongs to.

        ``Request.appId`` is now written during submission, but requests
        created before that change may still have it null — fall back to the
        ``app_name`` captured in ``rawRequest``, which is the same data the
        request was built from.
        """
        app = None
        if request.appId:
            app = self.appRepository.get_by_id(request.appId)
        if app is None and request.rawRequest:
            app_name = request.rawRequest.get("app_name")
            if app_name:
                app = self.appRepository.get_by_name(app_name)
        if app is None:
            raise NotFoundException(
                message="No app found for this request.",
                error_code="APP_NOT_FOUND",
            )
        return app

    @staticmethod
    def _parse_status(value: str) -> JobStatus:
        try:
            return JobStatus(value)
        except ValueError:
            raise BadRequestException(
                message=f"Unknown job status '{value}'.",
                error_code="INVALID_JOB_STATUS",
            )

    @staticmethod
    def _parse_step(value: str) -> JobStep:
        try:
            return JobStep(value)
        except ValueError:
            raise BadRequestException(
                message=f"Unknown job step '{value}'.",
                error_code="INVALID_JOB_STEP",
            )