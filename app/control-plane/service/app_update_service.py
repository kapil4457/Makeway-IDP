from sqlmodel import Session

from core import get_logger
from database.models.request import Request
from database.models.user import User
from database.models.app import App
from database.models.service import Service
from database.models.capability import Capability
from database.models.infra_requirement import InfraRequirement
from database.models.capability_access import CapabilityAccess
from dto.configs.capability import Capability as CapabilityDto, CapabilityConfig
from dto.configs.env_config import CapabilityAccessPatch, EnvConfig
from dto.enums.environment import Environment
from dto.enums.capability_status import CapabilityStatus
from dto.enums.capability_types import CapabilityType
from dto.enums.job_status import JobStatus
from dto.enums.job_step import JobStep
from database.models.job import Job
from dto.enums.request_status import RequestStatus
from dto.enums.request_type import RequestType
from dto.response.create_app import AppCreateResponse
from exceptions.base import InvalidRequestException, NotFoundException
from service.app_creation_queue import AppCreationQueue
from service.env_constraints import get_constraints
from repository.team_repository import TeamMemberRepository
from repository.app_repository import AppRepository
from repository.service_repository import ServiceRepository
from repository.cluster_repository import ClusterRepository
from repository.capability_repository import CapabilityRepository
from repository.infra_requirement_repository import InfraRequirementRepository
from repository.capability_access_repository import CapabilityAccessRepository
from repository.request_repository import RequestRepository
from repository.job_repository import JobRepository


# Request statuses that mean a pipeline run is still consuming this app's
# desired state. A new update must not interleave with one (shared Capability
# rows would flap status as both runs report).
_IN_FLIGHT_STATUSES = (RequestStatus.PENDING, RequestStatus.IN_PROGRESS)

logger = get_logger(__name__)


def _base_name(svc_name: str, env_value: str) -> str:
    """Strip the environment suffix the platform appends to service names."""
    return (
        svc_name.rsplit(f"-{env_value}", 1)[0]
        if svc_name.endswith(f"-{env_value}") else svc_name
    )


class AppUpdateService:

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
        app_name: str,
        updates: list[EnvConfig],
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

        if not updates:
            raise InvalidRequestException(
                message="Update payload must contain at least one environment entry."
            )
        envs = [update.env for update in updates]
        if len(set(envs)) != len(envs):
            raise InvalidRequestException(
                message="Each environment may appear at most once in an update."
            )

        """
            - services in an update are additions only (existing rows are reused)
            - capabilities are matched per (type, env): found -> config is
              overwritten (desired state), missing -> created like on create
            - anything not mentioned in the payload stays untouched
            - remove_services / remove_capabilities tear that item down for the
              env; their rows are only purged once the pipeline reports SUCCESS
              (internal_api_service._purge_removed_items), so every retry can
              still derive the XR names it has to delete
        """

        #region Validate the delta and resolve every name it references
        # env -> {base service name: Service row (existing or to-be-created)}
        services_by_env: dict[str, dict[str, Service | None]] = {}
        for update in updates:
            env = update.env
            cluster = self.clusterRepository.get_by_env(env.value)
            if cluster is None:
                raise InvalidRequestException(
                    message=f"No cluster is registered for environment '{env.value}'."
                )

            services: dict[str, Service | None] = {}
            for service in update.services:
                service_name = service.service_name or service.service_type.value
                svc_name = f"{service_name}-{env.value}"
                # app_id scope: svcName is only unique within an app — another
                # app may already run a service with the same row name.
                svc = self.serviceRepository.get_by_name(svc_name, app_id=app.appId)
                if svc is not None and svc.appId != app.appId:
                    raise InvalidRequestException(
                        message=f"Service name '{svc_name}' is already used by "
                                f"another application."
                    )
                services[service_name] = svc

            # Services the update doesn't mention but the env already runs are
            # equally valid access_to targets — resolve their base names too.
            for svc in self.serviceRepository.get_by_app(
                app.appId, cluster_id=cluster.clusterId
            ):
                base = (
                    svc.svcName.rsplit(f"-{env.value}", 1)[0]
                    if svc.svcName.endswith(f"-{env.value}") else svc.svcName
                )
                if base not in services:
                    services[base] = svc
            services_by_env[env.value] = services

            remove_services = set(update.remove_services or [])
            remove_capabilities = set(update.remove_capabilities or [])

            if env == Environment.PROD and (remove_services or remove_capabilities) \
                    and not confirm:
                raise InvalidRequestException(
                    message="Removing services/capabilities from 'prod' is "
                            "destructive; pass confirm=true to proceed."
                )

            # An item cannot be both added/updated and removed in one delta.
            for service in update.services:
                service_name = service.service_name or service.service_type.value
                if service_name in remove_services:
                    raise InvalidRequestException(
                        message=f"Service '{service_name}' cannot be added and "
                                f"removed in the same update."
                    )
            for capability in update.capabilities:
                if capability.config.type in remove_capabilities:
                    raise InvalidRequestException(
                        message=f"Capability '{capability.config.type}' cannot be "
                                f"added/updated and removed in the same update."
                    )

            # Every removal must name something this env actually has.
            for service_name in remove_services:
                if service_name not in services:
                    raise InvalidRequestException(
                        message=f"Service '{service_name}' does not exist in "
                                f"environment '{env.value}' and cannot be removed."
                    )
            for capability_type in remove_capabilities:
                if capability_type not in {t.value for t in CapabilityType}:
                    raise InvalidRequestException(
                        message=f"Unknown capability type '{capability_type}'."
                    )
                if self._find_capability(app, env.value, capability_type) is None:
                    raise InvalidRequestException(
                        message=f"App has no '{capability_type}' capability in "
                                f"environment '{env.value}' and cannot remove it."
                    )

            for capability in update.capabilities:
                self._validate_capability(update.env, capability.config,
                                          capability.access_to, services)
                grants_removed = set(capability.access_to) & remove_services
                if grants_removed:
                    raise InvalidRequestException(
                        message=f"Capability '{capability.config.type}' cannot "
                                f"grant access to removed service(s): "
                                f"{', '.join(sorted(grants_removed))}."
                    )

            # Access patches name capabilities by id — every entry must be
            # this app's capability in THIS environment, must not collide with
            # a removal or a re-declared capability, and on prod a patch that
            # shrinks access needs the same explicit sign-off removals do.
            for patch in update.update_access:
                self._validate_access_patch(
                    env, patch, services, confirm,
                    remove_services, remove_capabilities,
                    {capability.config.type for capability in update.capabilities},
                )

            self._validate_removal_orphans(
                app, env, remove_services, remove_capabilities, update.capabilities
            )
        #endregion

        #region Merge the delta into the app's desired state
        for update in updates:
            env = update.env
            cluster = self.clusterRepository.get_by_env(env.value)

            for service in update.services:
                service_name = service.service_name or service.service_type.value
                if services_by_env[env.value][service_name] is not None:
                    continue
                new_service = Service(
                    appId=app.appId,
                    clusterId=cluster.clusterId,
                    createdBy=user.email,
                    modifiedBy=user.email,
                    serviceType=service.service_type,
                    svcName=f"{service_name}-{env.value}"
                )
                new_service = self.serviceRepository.create(new_service)
                services_by_env[env.value][service_name] = new_service

            for capability in update.capabilities:
                self._upsert_capability(app, update.env, capability, user)

            # Patches run last so a patched capability's bindings end up
            # exactly as the patch states them, whatever the upserts added.
            for patch in update.update_access:
                self._apply_access_patch(update.env, patch, services, user)
        #endregion

        #region Register the request
        request = Request(
            idempotencyKey=idempotency_key,
            requestType=RequestType.UPDATE_APP,
            requestStatus=RequestStatus.PENDING,
            rawRequest={
                "app_name": app_name,
                "updates": [update.model_dump(mode="json") for update in updates],
            },
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

        # Single commit closes the unit of work: all rows written above are
        # persisted atomically. Nothing is enqueued until this succeeds.
        self.session.commit()
        #endregion

        #region Insert the request into the queue
        # Only enqueue. A failed publish must not fail the request: the unit of
        # work is already committed and durable, and a retry with the same
        # Idempotency-Key re-acknowledges the existing request.
        try:
            self.queue.publish(
                request_id=request.requestId,
                job_id=job.jobId,
            )
        except Exception:
            logger.error(
                "SQS publish failed for a committed app-update request — "
                "the consumer will not pick it up until republished",
                extra={"request_id": request.requestId, "job_id": job.jobId},
                exc_info=True,
            )
        #endregion

        return AppCreateResponse(
            message="App update request accepted",
            request_id=request.requestId,
            job_id=job.jobId,
            status="pending",
        )

    def _existing_response(self, existing_request: Request) -> AppCreateResponse:
        """
        Return the acknowledgement for a previously submitted request with the
        same idempotency key, mirroring the create endpoint: retrying the same
        update returns the original request/job identifiers.
        """
        existing_job = self.jobRepository.get_by_request_id(
            existing_request.requestId
        )

        return AppCreateResponse(
            message="App update request already exists",
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
        """No new update while a pipeline run is still reconciling this app.

        The desired-state tables are shared rows, so two concurrent runs would
        race on Capability status/outputs. Reject-and-retry keeps it simple.
        """
        latest = self.requestRepository.get_by_app(app.appId)
        if latest is not None and latest.requestStatus in _IN_FLIGHT_STATUSES:
            raise InvalidRequestException(
                message=(
                    f"App '{app.appName}' has a request still "
                    f"'{latest.requestStatus.value}'. Retry once it completes."
                ),
            )

    def _validate_capability(
        self,
        env: Environment,
        config: CapabilityConfig,
        access_to: list[str],
        services: dict[str, Service],
    ) -> None:
        if not config:
            raise InvalidRequestException(
                errors=[{"field": "capability_config",
                         "message": "Capability config must be specified for each capability."}],
                message="Capability configuration is required."
            )

        if config.type == CapabilityType.REL_DATABASE:
            capacity = config.capacity or 1
            constraints = get_constraints(env)
            max_allowed = constraints["max_database_capacity"]
            if capacity > max_allowed:
                raise InvalidRequestException(
                    message=f"Database capacity tier {capacity} exceeds "
                            f"environment {env.value} maximum "
                            f"allowed tier of {max_allowed}."
                )

        if not access_to:
            # Create tolerates empty access lists (it writes no access rows and
            # the capability becomes invisible to the workers). An update must
            # not create such an orphan.
            raise InvalidRequestException(
                errors=[{"field": "access_to",
                         "message": f"Capability '{config.type}' must grant access to at least one service."}],
                message="Capability access_to must not be empty on an update."
            )

        for service_name in access_to:
            if service_name not in services:
                raise InvalidRequestException(
                    message=f"Service '{service_name}' does not exist in "
                            f"environment '{env.value}'."
                )

    def _validate_access_patch(
        self,
        env: Environment,
        patch: CapabilityAccessPatch,
        services: dict[str, Service | None],
        confirm: bool,
        remove_services: set[str],
        remove_capabilities: set[str],
        declared_capability_types: set[str],
    ) -> None:
        """One update_access entry must name this app's capability in this env.

        Capability rows carry no app/env FK — ownership and scoping derive
        from access edges (same derivation the status read uses): the
        capability must hold at least one edge to a service of this app in
        this environment, otherwise the id names someone else's row or a
        capability of another env.
        """
        if not patch.access_to:
            raise InvalidRequestException(
                errors=[{"field": "access_to",
                         "message": "The replacement access list must grant "
                                    "access to at least one service."}],
                message="Capability access_to must not be empty on an update."
            )

        capability = self.capabilityRepository.get_by_id(patch.capability_id)
        if capability is None:
            raise NotFoundException(
                message=f"Capability {patch.capability_id} not found.",
                error_code="CAPABILITY_NOT_FOUND",
            )

        env_service_ids = {
            svc.svcId for svc in services.values() if svc is not None
        }
        env_accessors: set[str] = set()
        for access in self.capabilityAccessRepository.get_by_capability(
            capability.capabilityId
        ):
            if access.serviceId not in env_service_ids:
                continue
            svc = self.serviceRepository.get_by_id(access.serviceId)
            if svc is not None:
                env_accessors.add(_base_name(svc.svcName, env.value))

        if not env_accessors:
            raise InvalidRequestException(
                message=f"Capability {patch.capability_id} "
                        f"('{capability.capabilityType}') does not belong to "
                        f"this app in environment '{env.value}'."
            )

        if capability.capabilityType in remove_capabilities:
            raise InvalidRequestException(
                message=f"Capability '{capability.capabilityType}' cannot be "
                        f"access-patched and removed in the same update."
            )
        if capability.capabilityType in declared_capability_types:
            raise InvalidRequestException(
                message=f"Capability '{capability.capabilityType}' cannot be "
                        f"access-patched and re-declared in the same update."
            )

        grants_removed = set(patch.access_to) & remove_services
        if grants_removed:
            raise InvalidRequestException(
                message=f"Capability '{capability.capabilityType}' cannot "
                        f"grant access to removed service(s): "
                        f"{', '.join(sorted(grants_removed))}."
            )
        for service_name in patch.access_to:
            if service_name not in services:
                raise InvalidRequestException(
                    message=f"Service '{service_name}' does not exist in "
                            f"environment '{env.value}'."
                )

        if env == Environment.PROD and not confirm:
            if env_accessors - set(patch.access_to):
                raise InvalidRequestException(
                    message="Removing capability access from 'prod' is "
                            "destructive; pass confirm=true to proceed."
                )

    def _validate_removal_orphans(
        self,
        app: App,
        env: Environment,
        remove_services: set[str],
        remove_capabilities: set[str],
        payload_capabilities: list[CapabilityDto],
    ) -> None:
        """A capability that survives the update must keep an accessor.

        Removing a service takes its access bindings with it; if that leaves a
        capability (not itself being removed) with zero accesses, it would
        become invisible to the workers — the update must name it for removal
        too, or keep another accessor. Accesses the payload grants count as
        post-update accesses, so removing a service while simultaneously
        re-granting the capability elsewhere is accepted.
        """
        if not remove_services:
            return

        # access_to the payload grants per capability type (the modify path
        # adds those rows) — they count as post-update accesses.
        payload_accesses: dict[str, set[str]] = {}
        for capability in payload_capabilities:
            payload_accesses.setdefault(
                capability.config.type, set()
            ).update(capability.access_to)

        for cap in self.capabilityRepository.get_by_app(app.appId):
            if cap.capabilityType in remove_capabilities:
                continue
            cap_env: str | None = None
            current_accessors: set[str] = set()
            for access in self.capabilityAccessRepository.get_by_capability(
                cap.capabilityId
            ):
                svc = self.serviceRepository.get_by_id(access.serviceId)
                if svc is None:
                    continue
                cluster = self.clusterRepository.get_by_id(svc.clusterId)
                if cluster is None:
                    continue
                if cap_env is None:
                    cap_env = cluster.environment
                if cluster.environment == env.value:
                    base = (
                        svc.svcName.rsplit(f"-{env.value}", 1)[0]
                        if svc.svcName.endswith(f"-{env.value}") else svc.svcName
                    )
                    current_accessors.add(base)
            if cap_env != env.value:
                continue

            future_accessors = (
                current_accessors - remove_services
            ) | payload_accesses.get(cap.capabilityType, set())
            if not future_accessors:
                raise InvalidRequestException(
                    message=f"Removing services {sorted(remove_services)} would "
                            f"orphan capability '{cap.capabilityType}' in "
                            f"environment '{env.value}': remove the capability "
                            f"too, or keep another accessor."
                )

    # ------------------------------------------------------------------ #
    # Desired-state writes
    # ------------------------------------------------------------------ #

    def _upsert_capability(
        self,
        app: App,
        env: Environment,
        capability: CapabilityDto,
        user: User,
    ) -> None:
        """Update-or-create one capability's desired state for one env.

        A capability is matched on (capabilityType, access-derived env) — the
        same derivation the request-details read uses. A match overwrites its
        InfraRequirement config; no match creates the rows the create flow
        would have. Existing access bindings are never removed.
        """
        config = capability.config

        existing = self._find_capability(app, env.value, config.type)
        if existing is None:
            new_capability = Capability(
                capabilityType=config.type,
                createdBy=user.email,
                modifiedBy=user.email,
                status=CapabilityStatus.PENDING
            )
            existing = self.capabilityRepository.create(new_capability)

            new_infrastructure_requirement = InfraRequirement(
                config=config.model_dump(mode="json"),
                capabilityId=existing.capabilityId,
                createdBy=user.email,
                modifiedBy=user.email
            )
            self.infraRequirementRepository.create(new_infrastructure_requirement)
        else:
            infra = self.infraRequirementRepository.get_by_capability(
                existing.capabilityId
            )
            if infra is None:
                raise NotFoundException(
                    message=f"No infra requirement for capability {existing.capabilityId}.",
                    error_code="INFRA_REQUIREMENT_NOT_FOUND",
                )
            infra.config = config.model_dump(mode="json")
            infra.errorMessage = None
            infra.modifiedBy = user.email

            existing.status = CapabilityStatus.PENDING
            existing.errorMessage = None
            existing.modifiedBy = user.email

        for service_name in capability.access_to:
            # app_id scope: another app may run a service with the same row
            # name ({base}-{env}) — binding an edge to it would make this
            # capability invisible to its own app (status read and worker
            # claims both derive through access edges).
            svc = self.serviceRepository.get_by_name(
                f"{service_name}-{env.value}", app_id=app.appId
            )
            if svc is None:
                raise InvalidRequestException(
                    message=f"Service '{service_name}' does not exist in "
                            f"environment '{env.value}'."
                )
            already = any(
                access.serviceId == svc.svcId
                for access in self.capabilityAccessRepository.get_by_capability(
                    existing.capabilityId
                )
            )
            if already:
                continue
            capability_access = CapabilityAccess(
                capabilityId=existing.capabilityId,
                serviceId=svc.svcId,
                createdBy=user.email,
                modifiedBy=user.email
            )
            self.capabilityAccessRepository.create(capability_access)

    def _apply_access_patch(
        self,
        env: Environment,
        patch: CapabilityAccessPatch,
        services: dict[str, Service | None],
        user: User,
    ) -> None:
        """Replace the capability's access bindings for one environment.

        Runs after service creation and capability upserts, so every name in
        `services` resolves to a real row. Only edges to THIS env's services
        participate — a capability row can hold bindings across environments,
        and those are not this patch's concern. Edge rows are desired-state
        metadata: written at submit like config overwrites, not deferred to
        the success purge. The capability re-enters reconciliation either way
        (a grant means new secret injection; a revoke means it must stop).
        """
        svc_ids = {
            _base_name(svc.svcName, env.value): svc.svcId
            for svc in services.values() if svc is not None
        }
        desired_ids = {svc_ids[name] for name in patch.access_to}

        current: dict[int, CapabilityAccess] = {}
        for access in self.capabilityAccessRepository.get_by_capability(
            patch.capability_id
        ):
            if access.serviceId in set(svc_ids.values()):
                current[access.serviceId] = access

        for service_id, access in current.items():
            if service_id not in desired_ids:
                self.capabilityAccessRepository.delete(access)
        for service_id in desired_ids - set(current):
            self.capabilityAccessRepository.create(CapabilityAccess(
                capabilityId=patch.capability_id,
                serviceId=service_id,
                createdBy=user.email,
                modifiedBy=user.email,
            ))

        capability = self.capabilityRepository.get_by_id(patch.capability_id)
        if capability is not None:
            capability.status = CapabilityStatus.PENDING
            capability.errorMessage = None
            capability.modifiedBy = user.email

    def _find_capability(
        self,
        app: App,
        env: str,
        capability_type: str,
    ) -> Capability | None:
        """The app's capability of `capability_type` scoped to `env`.

        Capability rows carry no env FK — their environment is derived from
        the services they grant access to (CapabilityAccess -> Service ->
        Cluster), exactly as ``get_request_details`` derives it.
        """
        for cap in self.capabilityRepository.get_by_app(app.appId):
            if cap.capabilityType != capability_type:
                continue
            for access in self.capabilityAccessRepository.get_by_capability(
                cap.capabilityId
            ):
                svc = self.serviceRepository.get_by_id(access.serviceId)
                if svc is None:
                    continue
                cluster = self.clusterRepository.get_by_id(svc.clusterId)
                if cluster is not None and cluster.environment == env:
                    return cap
        return None