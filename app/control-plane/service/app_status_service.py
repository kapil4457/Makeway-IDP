"""Read-side aggregation for ``GET /app/{app_name}/status``.

Companion to the write-side reconcilers (app creation + internal status
callbacks): it walks the persisted reconcile state (app, services per env,
capabilities + infra, deployments, access bindings, latest request/job) and
shapes it into the per-environment snapshot the UI renders.

Nothing in here mutates or raises on missing infra detail — the response
carries ``dataSource="persisted"`` markers and honest ``unknown`` health so a
status endpoint reports reality instead of erroring. Only authentication and
authorization 404/403 before the read.
"""

from datetime import datetime

from sqlmodel import Session

from core import get_logger
from database.models.app import App
from database.models.capability import Capability
from database.models.capability_access import CapabilityAccess
from database.models.deployment_setup import DeploymentSetup
from database.models.job import Job
from database.models.request import Request
from database.models.service import Service
from database.models.user import User
from dto.enums.connectivity_status import ConnectivityStatus
from dto.enums.service_health import ServiceHealth
from dto.response.app_status import (
    AppStatusResponse,
    CapabilityStatusInfo,
    ClusterStatus,
    ConnectivityStatusInfo,
    DeploymentStatusInfo,
    EnvStatus,
    InfraStatus,
    RequestStatusBrief,
    ServiceStatus,
)
from exceptions.base import ForbiddenException, NotFoundException
from repository.app_repository import AppRepository
from repository.capability_access_repository import CapabilityAccessRepository
from repository.capability_repository import CapabilityRepository
from repository.cluster_repository import ClusterRepository
from repository.deployment_setup_repository import DeploymentSetupRepository
from repository.infra_requirement_repository import InfraRequirementRepository
from repository.job_repository import JobRepository
from repository.request_repository import RequestRepository
from repository.service_repository import ServiceRepository
from repository.team_repository import TeamMemberRepository


logger = get_logger(__name__)


class AppStatusService:

    def __init__(
        self,
        session: Session,
        appRepository: AppRepository,
        teamMemberRepository: TeamMemberRepository,
        clusterRepository: ClusterRepository,
        serviceRepository: ServiceRepository,
        capabilityRepository: CapabilityRepository,
        capabilityAccessRepository: CapabilityAccessRepository,
        infraRequirementRepository: InfraRequirementRepository,
        deploymentSetupRepository: DeploymentSetupRepository,
        requestRepository: RequestRepository,
        jobRepository: JobRepository,
    ):
        self.session = session
        self.appRepository = appRepository
        self.teamMemberRepository = teamMemberRepository
        self.clusterRepository = clusterRepository
        self.serviceRepository = serviceRepository
        self.capabilityRepository = capabilityRepository
        self.capabilityAccessRepository = capabilityAccessRepository
        self.infraRequirementRepository = infraRequirementRepository
        self.deploymentSetupRepository = deploymentSetupRepository
        self.requestRepository = requestRepository
        self.jobRepository = jobRepository

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def get_app_status(self, app_name: str, current_user: User) -> AppStatusResponse:
        """Status snapshot for an app, per environment.

        Validations before any read:
          1. App must exist (404 APP_NOT_FOUND).
          2. Current user must be a member of the team that owns the app
             (403 FORBIDDEN). Uses the same membership lookup the create flow
             enforces.
        """
        app = self.appRepository.get_by_name(app_name)
        if app is None:
            raise NotFoundException(
                message=f"App '{app_name}' does not exist.",
                error_code="APP_NOT_FOUND",
            )

        if not self._user_owns_app(current_user, app):
            raise ForbiddenException(
                message=(
                    f"User is not a member of the team that owns app "
                    f"'{app_name}'."
                ),
                error_code="APP_ACCESS_FORBIDDEN",
            )

        request = self.requestRepository.get_by_app(app.appId)
        job = self.jobRepository.get_by_request_id(request.requestId) if request else None

        services = self.serviceRepository.get_by_app(app.appId)

        # One env block per distinct cluster serving this app's services;
        # first-seen order so the response is stable for the same data.
        env_groups: dict[int, list[Service]] = {}
        for svc in services:
            env_groups.setdefault(svc.clusterId, []).append(svc)

        env_statuses: list[EnvStatus] = []
        for cluster_id, env_services in env_groups.items():
            env_statuses.append(
                self._status_for_env(
                    app=app,
                    cluster_id=cluster_id,
                    services=env_services,
                )
            )

        team_name = None
        if app.teamId:
            team = self.teamMemberRepository.get_team_by_id(app.teamId)
            if team is not None:
                team_name = team.teamName

        return AppStatusResponse(
            appId=app.appId,
            appName=app.appName,
            teamName=team_name,
            appRepoUrl=app.appRepoUrl,
            gitOpsPath=app.gitOpsPath,
            request=self._request_status(request, job),
            envStatuses=env_statuses,
        )

    # ------------------------------------------------------------------ #
    # Per-environment aggregation
    # ------------------------------------------------------------------ #

    def _status_for_env(
        self,
        app: App,
        cluster_id: int,
        services: list[Service],
    ) -> EnvStatus:
        cluster = self.clusterRepository.get_by_id(cluster_id)

        service_statuses: list[ServiceStatus] = []
        service_by_id: dict[int, Service] = {}
        errors: list[str] = []

        for svc in services:
            service_by_id[svc.svcId] = svc
            dep = self.deploymentSetupRepository.get_by_service_id(svc.svcId)
            health, health_timestamp = self._derive_service_health(svc, dep)
            service_statuses.append(
                ServiceStatus(
                    svcId=svc.svcId,
                    svcName=svc.svcName,
                    serviceType=svc.serviceType.value,
                    health=health,
                    healthSource="persisted",
                    lastUpdatedAt=health_timestamp,
                    deployment=self._deployment_status_info(dep),
                    error=dep.errorMessage if dep else None,
                )
            )
            if dep is not None and dep.errorMessage:
                errors.append(f"service {svc.svcName}: {dep.errorMessage}")

        capabilities = self.capabilityRepository.get_by_app(app.appId)
        svc_ids_in_env = set(service_by_id)

        # Capabilities are env-scoped through their CapabilityAccess edges: a
        # capability belongs to an env only when a service of that env is bound
        # to it. Unbound capabilities appear in no env block.
        env_cap_ids: set[int] = set()
        for cap in capabilities:
            for access in self.capabilityAccessRepository.get_by_capability(cap.capabilityId):
                if access.serviceId in svc_ids_in_env:
                    env_cap_ids.add(cap.capabilityId)
                    break

        capability_statuses: list[CapabilityStatusInfo] = []
        capability_by_id: dict[int, Capability] = {}

        for cap in capabilities:
            if cap.capabilityId not in env_cap_ids:
                continue
            capability_by_id[cap.capabilityId] = cap
            infra = self.infraRequirementRepository.get_by_capability(cap.capabilityId)
            capability_statuses.append(
                CapabilityStatusInfo(
                    capabilityId=cap.capabilityId,
                    capabilityType=cap.capabilityType,
                    name=self._capability_name(cap, infra.config if infra else None),
                    status=cap.status.value,
                    statusSource="persisted",
                    infra=(
                        InfraStatus(
                            config=infra.config,
                            outputRef=infra.outputRef,
                            secretRef=infra.secretRef,
                        )
                        if infra is not None
                        else None
                    ),
                    error=infra.errorMessage if (infra and infra.errorMessage) else cap.errorMessage,
                )
            )
            err = infra.errorMessage if (infra and infra.errorMessage) else cap.errorMessage
            if err:
                errors.append(f"capability {cap.capabilityType} (id {cap.capabilityId}): {err}")

        # Connectivity edges — every capability granted to a service in this env.
        connectivity: list[ConnectivityStatusInfo] = []
        for cap in capabilities:
            if cap.capabilityId not in env_cap_ids:
                continue
            for access in self.capabilityAccessRepository.get_by_capability(cap.capabilityId):
                if access.serviceId not in svc_ids_in_env:
                    continue
                connectivity.append(
                    ConnectivityStatusInfo(
                        serviceSvcId=access.serviceId,
                        capabilityId=cap.capabilityId,
                        accessConfigured=True,
                        status=ConnectivityStatus.CONFIGURED,
                        source="persisted",
                    )
                )

        return EnvStatus(
            env=cluster.environment if cluster else f"cluster-{cluster_id}",
            cluster=ClusterStatus(
                clusterId=cluster_id,
                clusterName=cluster.clusterName if cluster else "unknown-cluster",
                environment=cluster.environment if cluster else "unknown",
            ),
            services=service_statuses,
            capabilities=capability_statuses,
            connectivity=connectivity,
            errors=errors,
        )

    def _derive_service_health(
        self,
        svc: Service,
        dep: DeploymentSetup | None,
    ) -> tuple[ServiceHealth, datetime | None]:
        """Best-known service health from persisted rollout state.

        A ``success``/``synced`` deployment with no error is healthy; a failed
        deployment is unhealthy; everything else (untouched setup, pending
        reconcile) stays UNKNOWN — the endpoint reports what a reporter has
        actually recorded instead of guessing.
        """
        if dep is None:
            return ServiceHealth.UNKNOWN, None

        timestamp = dep.lastSyncedAt or dep.modifiedAt
        if dep.status == "success" and not dep.errorMessage:
            return ServiceHealth.HEALTHY, timestamp
        if dep.status == "failed" or dep.errorMessage:
            return ServiceHealth.UNHEALTHY, timestamp
        return ServiceHealth.UNKNOWN, timestamp

    @staticmethod
    def _capability_name(cap: Capability, config: dict | None) -> str | None:
        """A display name for a capability: the config's ``name`` where the
        capability type has one (rel_database, queue), else ``None``."""

        if not isinstance(config, dict):
            return None
        name = config.get("name")
        return name if isinstance(name, str) else None

    @staticmethod
    def _deployment_status_info(dep: DeploymentSetup | None) -> DeploymentStatusInfo | None:
        if dep is None:
            return None
        return DeploymentStatusInfo(
            status=dep.status,
            argocdAppName=dep.argocdAppName,
            lastSyncedAt=dep.lastSyncedAt,
            errorMessage=dep.errorMessage,
        )

    def _request_status(self, request: Request | None, job: Job | None) -> RequestStatusBrief | None:
        if request is None:
            return None
        return RequestStatusBrief(
            requestId=request.requestId,
            requestStatus=request.requestStatus.value,
            jobId=job.jobId if job else None,
            jobStep=job.step.value if job else None,
            jobStatus=job.status.value if job else None,
            executionArn=job.stepFunctionExecutionArn if job else None,
            error=job.errorDetail if job else None,
        )

    def _user_owns_app(self, current_user: User, app: App) -> bool:
        """Matches the authorization the create flow enforces: an active
        team membership in the team that owns the app."""

        team = self.teamMemberRepository.get_team_by_id(app.teamId)
        if team is None:
            return False
        return self.teamMemberRepository.get_by_user_and_team(
            current_user.userId,
            team.teamName,
        )