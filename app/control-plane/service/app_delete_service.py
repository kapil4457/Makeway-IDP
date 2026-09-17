from sqlmodel import Session, delete, select

from core import get_logger
from database.models.request import Request
from database.models.user import User
from database.models.app import App
from database.models.job import Job
from dto.enums.environment import Environment
from dto.enums.job_status import JobStatus
from dto.enums.job_step import JobStep
from dto.enums.request_status import RequestStatus
from dto.enums.request_type import RequestType
from dto.response.app_purge import AppPurgeResponse
from dto.response.create_app import AppCreateResponse
from exceptions.base import InvalidRequestException, NotFoundException
from service.app_creation_queue import AppCreationQueue
from repository.team_repository import TeamMemberRepository
from repository.app_repository import AppRepository
from repository.cluster_repository import ClusterRepository
from repository.service_repository import ServiceRepository
from repository.request_repository import RequestRepository
from repository.job_repository import JobRepository


# Request statuses that mean a pipeline run is still consuming this app's
# desired state. A delete must not interleave with one (shared Capability
# rows would flap status as both runs report).
_IN_FLIGHT_STATUSES = (RequestStatus.PENDING, RequestStatus.IN_PROGRESS)

logger = get_logger(__name__)


class AppDeleteService:

    def __init__(
        self,
        session: Session,
        queue: AppCreationQueue,
        teamMemberRepository: TeamMemberRepository,
        appRepository: AppRepository,
        clusterRepository: ClusterRepository,
        serviceRepository: ServiceRepository,
        requestRepository: RequestRepository,
        jobRepository: JobRepository,
    ):
        self.session = session
        self.queue = queue
        self.teamMemberRepository = teamMemberRepository
        self.appRepository = appRepository
        self.clusterRepository = clusterRepository
        self.serviceRepository = serviceRepository
        self.requestRepository = requestRepository
        self.jobRepository = jobRepository

    def submit(
        self,
        app_name: str,
        env: Environment,
        user: User,
        idempotency_key: str,
        confirm: bool = False,
    ) -> AppCreateResponse:

        existing = self.requestRepository \
            .get_by_idempotency_key(
                idempotency_key
            )

        if existing:
            return self._existing_response(existing)

        app = self._resolve_app(app_name, user)

        self._reject_in_flight(app)

        """
            - no rows are deleted here: the desired state stays intact until
              the pipeline reports SUCCESS, so every retry can still derive
              the deterministic XR names it has to tear down
              (internal_api_service._purge_env runs on the success callback)
            - the request snapshot names the target: app_name + env
        """

        #region Validate the teardown target
        cluster = self.clusterRepository.get_by_env(env.value)
        if cluster is None:
            raise InvalidRequestException(
                message=f"No cluster is registered for environment '{env.value}'."
            )

        services = self.serviceRepository.get_by_app(
            app.appId, cluster_id=cluster.clusterId
        )
        if not services:
            raise InvalidRequestException(
                message=f"App '{app_name}' has no services in environment "
                        f"'{env.value}'."
            )

        if env == Environment.PROD and not confirm:
            raise InvalidRequestException(
                message="Deleting a 'prod' environment is destructive; "
                        "pass confirm=true to proceed."
            )
        #endregion

        #region Register the request
        request = Request(
            idempotencyKey=idempotency_key,
            requestType=RequestType.DELETE_APP,
            requestStatus=RequestStatus.PENDING,
            rawRequest={"app_name": app_name, "env": env.value},
            appId=app.appId,
        )
        request = self.requestRepository.create(request)
        #endregion

        #region Create a job to be processed
        job = Job(
            requestId=request.requestId,
            step=JobStep.CREATE_PROJECT,
            status=JobStatus.PENDING,
        )
        job = self.jobRepository.create(job)

        # Single commit closes the unit of work. Nothing is enqueued until
        # this succeeds.
        self.session.commit()
        #endregion

        #region Insert the request into the queue
        # A failed publish must not fail the request: the unit of work is
        # already committed and durable, and a retry with the same
        # Idempotency-Key re-acknowledges the existing request.
        try:
            self.queue.publish(
                request_id=request.requestId,
                job_id=job.jobId,
            )
        except Exception:
            logger.error(
                "SQS publish failed for a committed app-delete request — "
                "the consumer will not pick it up until republished",
                extra={"request_id": request.requestId, "job_id": job.jobId},
                exc_info=True,
            )
        #endregion

        return AppCreateResponse(
            message="App delete request accepted",
            request_id=request.requestId,
            job_id=job.jobId,
            status="pending",
        )

    def purge_app(
        self,
        app_name: str,
        user: User,
        confirm: bool = False,
    ) -> AppPurgeResponse:
        """Purge an app's record after every environment is gone.

        The recovery exit for the zombie state: an app whose environments were
        all torn down keeps its ``appName`` (unique) and its audit trail
        (requests/jobs), so it can be neither updated nor re-created. This
        deletes those rows synchronously — no pipeline run, nothing left to
        reconcile — in FK order (jobs → requests → app). The services
        repository on GitHub is deliberately kept: deleting it is a manual,
        out-of-band decision.

        Only the terminal state qualifies: any service row means desired state
        still exists and must go through the environment-scoped delete first.
        """
        app = self._resolve_app(app_name, user)

        self._reject_in_flight(app)

        services = self.serviceRepository.get_by_app(app.appId)
        if services:
            raise InvalidRequestException(
                message=(
                    f"App '{app_name}' still has {len(services)} service row(s) "
                    f"in its desired state. Delete its environments first — "
                    f"'Delete app' only clears the record once every "
                    f"environment is gone."
                )
            )

        if not confirm:
            raise InvalidRequestException(
                message=(
                    f"Deleting app '{app_name}' removes its record and audit "
                    f"trail permanently; pass confirm=true to proceed."
                )
            )

        purged = self._purge_app_rows(app)
        self.session.commit()

        logger.info(
            "App record purged",
            extra={
                "extra_fields": {
                    "app_name": app.appName,
                    "app_id": app.appId,
                    "purged": purged,
                }
            },
        )
        return AppPurgeResponse(appName=app.appName, purged=purged)

    def _purge_app_rows(self, app: App) -> dict[str, int]:
        """Delete the app's audit rows, children first, then the app itself.

        Service-scoped tables (services, capabilities, namespaces, bindings)
        are unreachable here: the caller guaranteed zero service rows, and
        every one of those rows hangs off a service through a NOT NULL FK.
        Flushed by the caller's single ``session.commit()``.
        """
        request_ids = list(
            self.session.exec(
                select(Request.requestId).where(Request.appId == app.appId)
            ).all()
        )

        purged: dict[str, int] = {}
        if request_ids:
            purged["jobs"] = self.session.exec(
                delete(Job).where(Job.requestId.in_(request_ids))
            ).rowcount or 0
            purged["requests"] = self.session.exec(
                delete(Request).where(Request.requestId.in_(request_ids))
            ).rowcount or 0

        self.session.delete(app)
        purged["app"] = 1
        return purged

    def _existing_response(self, existing_request: Request) -> AppCreateResponse:
        """
        Return the acknowledgement for a previously submitted request with the
        same idempotency key, mirroring the create/update endpoints: retrying
        the same delete returns the original request/job identifiers.
        """
        existing_job = self.jobRepository.get_by_request_id(
            existing_request.requestId
        )

        return AppCreateResponse(
            message="App delete request already exists",
            request_id=existing_request.requestId,
            job_id=existing_job.jobId if existing_job else 0,
            status=existing_request.requestStatus.value,
        )

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def _resolve_app(self, app_name: str, user: User) -> App:
        app = self.appRepository.get_by_name(app_name)
        if app is None:
            raise NotFoundException(
                message=f"App '{app_name}' not found.",
                error_code="APP_NOT_FOUND",
            )

        team = self.teamMemberRepository.get_team_by_id(app.teamId)
        if team is None or not self.teamMemberRepository.get_by_user_and_team(
            user.userId,
            team.teamName
        ):
            raise InvalidRequestException(
                message=f"User is not a member of the team owning app '{app_name}'."
            )

        return app

    def _reject_in_flight(self, app: App) -> None:
        """No delete while a pipeline run is still reconciling this app.

        The desired-state tables are shared rows, so a delete interleaving
        with a create/update would race on Capability status/outputs.
        Reject-and-retry keeps it simple.
        """
        latest = self.requestRepository.get_by_app(app.appId)
        if latest is not None and latest.requestStatus in _IN_FLIGHT_STATUSES:
            raise InvalidRequestException(
                message=(
                    f"App '{app.appName}' has a request still "
                    f"'{latest.requestStatus.value}'. Retry once it completes."
                ),
            )