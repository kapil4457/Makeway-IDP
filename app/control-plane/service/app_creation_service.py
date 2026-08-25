from sqlmodel import Session

from database.models.job import Job
from database.models.request import Request
from database.models.user import User
from database.models.app import App
from database.models.service import Service
from database.models.capability import Capability
from database.models.infra_requirement import InfraRequirement
from database.models.capability_access import CapabilityAccess
from dto.configs.app_config import AppConfig
from dto.enums.job_status import JobStatus
from dto.enums.job_step import JobStep
from dto.enums.request_status import RequestStatus
from dto.enums.request_type import RequestType
from dto.response.create_app import AppCreateResponse
from service.app_creation_queue import AppCreationQueue
from repository.team_repository import TeamMemberRepository
from repository.app_repository import AppRepository
from repository.service_repository import ServiceRepository
from repository.cluster_repository import ClusterRepository
from repository.capability_repository import CapabilityRepository
from repository.infra_requirement_repository import InfraRequirementRepository
from repository.capability_access_repository import CapabilityAccessRepository
from repository.request_repository import RequestRepository
from repository.job_repository import JobRepository
from exceptions.base import InvalidRequestException
from service.env_constraints import get_constraints
from dto.enums.capability_status import CapabilityStatus
from dto.enums.capability_types import CapabilityType


class AppCreationService:

    def __init__(
        self,
        session: Session,
        queue: AppCreationQueue,
        teamMemberRepository: TeamMemberRepository,
        appRepository: AppRepository,
        clusterRepository: ClusterRepository,
        serviceRepository: ServiceRepository,
        capabilityRepository: CapabilityRepository,
        infraRequirementRepository: InfraRequirementRepository,
        capabilityAccessRepository: CapabilityAccessRepository,
        requestRepository: RequestRepository,
        jobRepository: JobRepository,
    ):
        self.session = session
        self.queue = queue
        self.teamMemberRepository = teamMemberRepository
        self.appRepository = appRepository
        self.clusterRepository = clusterRepository
        self.serviceRepository = serviceRepository
        self.capabilityRepository = capabilityRepository
        self.infraRequirementRepository = infraRequirementRepository
        self.capabilityAccessRepository = capabilityAccessRepository
        self.requestRepository = requestRepository
        self.jobRepository = jobRepository

    def submit(
        self,
        app_config: AppConfig,
        user: User,
        idempotency_key: str,
    ) -> AppCreateResponse:

        existing = self.requestRepository \
            .get_by_idempotency_key(
                idempotency_key
            )

        if existing:
            return self._existing_response(existing)

        self.validateRequest(app_config, user)

        """
            - for each service, insert an entry for each selected environment
            - for each capability, maintain which service has access to them
        """

        #region Register the application
        # Resolve the team name into the team's DB primary key (FK on App).
        team_id = self.teamMemberRepository.get_team_id_by_name(
            app_config.team_name
        )

        app = App(
            appName=app_config.app_name,
            createdBy=user.email,
            teamId=team_id,
            modifiedBy=user.email
        )

        # Repositories only flush; the single commit below makes the whole
        # registration atomic (app + services + capabilities + request + job).
        app = self.appRepository.create(app)
       #endregion

        #region Register service per environment
        for env_config in app_config.env_config:
            env = env_config.env
            services = env_config.services
            capabilities = env_config.capabilities

            cluster = self.clusterRepository.get_by_env(env)
            if cluster is None:
                raise InvalidRequestException(
                    message=f"No cluster is registered for environment '{env.value}'."
                )

            for service in services:
                service_name = service.service_name or service.service_type.value
                new_service = Service(
                    appId=app.appId,
                    clusterId=cluster.clusterId,
                    createdBy=user.email,
                    modifiedBy=user.email,
                    serviceType=service.service_type,
                    svcName=f"{service_name}-{env.value}"
                )
                self.serviceRepository.create(new_service)

            for capability in capabilities:
                config = capability.config
                new_capability = Capability(
                    capabilityType=config.type,
                    createdBy=user.email,
                    modifiedBy=user.email,
                    status=CapabilityStatus.PENDING
                )
                new_capability = self.capabilityRepository.create(new_capability)

                new_infrastructure_requirement = InfraRequirement(
                    config=config.model_dump(mode="json"),
                    capabilityId=new_capability.capabilityId,
                    createdBy=user.email,
                    modifiedBy=user.email
                )
                self.infraRequirementRepository.create(new_infrastructure_requirement)

                for service_name in capability.access_to:
                    service_obj = self.serviceRepository.get_by_name(
                        f"{service_name}-{env.value}"
                    )
                    if service_obj is None:
                        raise InvalidRequestException(
                            message=f"Service '{service_name}' does not exist in "
                                    f"environment '{env.value}'."
                        )

                    capability_access = CapabilityAccess(
                        capabilityId=new_capability.capabilityId,
                        serviceId=service_obj.svcId,
                        createdBy=user.email,
                        modifiedBy=user.email
                    )
                    self.capabilityAccessRepository.create(capability_access)
        #endregion

        #region Register the request
        request = Request(
            idempotencyKey=idempotency_key,
            requestType=RequestType.CREATE_APP,
            requestStatus=RequestStatus.PENDING,
            rawRequest=app_config.model_dump(mode="json"),
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

        # Single commit closes the unit of work: all rows written above are
        # persisted atomically. Nothing is enqueued until this succeeds.
        self.session.commit()
        #endregion

        #region Insert the request into the queue
        # Only enqueue.
        self.queue.publish(
            request_id=request.requestId,
            job_id=job.jobId,
        )
        #endregion

        return AppCreateResponse(
            message="App creation request accepted",
            request_id=request.requestId,
            job_id=job.jobId,
            status="pending",
        )

    def _existing_response(self, existing_request: Request) -> AppCreateResponse:
        """
        Return the acknowledgement for a previously submitted request with the
        same idempotency key. This makes the endpooint idempotent: retrying the
        same payload returns the original request/job identifiers instead of
        creating duplicates.
        """
        existing_job = self.jobRepository.get_by_request_id(
            existing_request.requestId
        )

        return AppCreateResponse(
            message="App creation request already exists",
            request_id=existing_request.requestId,
            job_id=existing_job.jobId if existing_job else 0,
            status=existing_request.requestStatus.value,
        )


    def validateRequest(self, app_config: AppConfig, user: User):
        """
        This is used to validate the incoming request by applying :
            - Environment specific constraints
            - perform user authorization (check if user is part of the team)
            - perform null checks
        """

        # Validation 1: Check if user is part of the team requesting the app
        # Use repository to check team membership
        if not self.teamMemberRepository.get_by_user_and_team(
            user.userId,
            app_config.team_name
        ):
            raise InvalidRequestException(
                errors=[{"field": "team_name", "message": f"User is not a member of team '{app_config.team_name}'."}],
                message="User is not a member of the requested team."
            )

        # Validation 2: Environment-specific constraints
        # Validate env config and capabilities against system-defined constraints
        for env_cfg in app_config.env_config:
            # Check that environment is valid
            if not env_cfg.env:
                raise InvalidRequestException(
                    message="Environment must be specified for each env_config entry."
                )

            # Service types are validated by the DTO layer (Pydantic enum field),
            # so no extra service-type checks are needed here.

            # Validate capabilities config per environment
            for cap_cfg in env_cfg.capabilities:
                if not cap_cfg.config:
                    raise InvalidRequestException(
                        errors=[{"field": "capability_config", "message": "Capability config must be specified for each capability."}],
                        message="Capability configuration is required."
                    )

                # Validate database capacity against environment constraints
                cap_config = cap_cfg.config
                if cap_config.type == CapabilityType.REL_DATABASE:
                    capacity = cap_config.capacity or 1
                    constraints = get_constraints(env_cfg.env)
                    max_allowed = constraints["max_database_capacity"]
                    if capacity > max_allowed:
                        raise InvalidRequestException(
                            message=f"Database capacity tier {capacity} exceeds "
                                    f"environment {env_cfg.env.value} maximum "
                                    f"allowed tier of {max_allowed}."
                        )