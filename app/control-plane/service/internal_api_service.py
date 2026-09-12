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
from database.models.capability import Capability
from database.models.job import Job
from database.models.request import Request
from dto.enums.capability_status import CapabilityStatus
from dto.enums.job_status import JobStatus
from dto.enums.job_step import JobStep
from dto.enums.request_status import RequestStatus
from dto.enums.request_type import RequestType
from dto.request.internal import (
    InternalCapabilityOutput,
    InternalDeploymentSetupReport,
    InternalStatusUpdateRequest,
)
from exceptions.base import (
    BadRequestException,
    NotFoundException,
)
from repository.app_repository import AppRepository
from repository.capability_access_repository import CapabilityAccessRepository
from repository.capability_repository import CapabilityRepository
from repository.cluster_repository import ClusterRepository
from repository.deployment_setup_repository import DeploymentSetupRepository
from repository.infra_requirement_repository import InfraRequirementRepository
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
        capabilityRepository: CapabilityRepository,
        capabilityAccessRepository: CapabilityAccessRepository,
        infraRequirementRepository: InfraRequirementRepository,
        deploymentSetupRepository: DeploymentSetupRepository,
    ):
        self.session = session
        self.requestRepository = requestRepository
        self.jobRepository = jobRepository
        self.appRepository = appRepository
        self.serviceRepository = serviceRepository
        self.clusterRepository = clusterRepository
        self.capabilityRepository = capabilityRepository
        self.capabilityAccessRepository = capabilityAccessRepository
        self.infraRequirementRepository = infraRequirementRepository
        self.deploymentSetupRepository = deploymentSetupRepository

    # ------------------------------------------------------------------ #
    # Read-side: what the state machine needs to execute a step
    # ------------------------------------------------------------------ #

    def get_request_details(self, request_id: int) -> dict:
        """Return the app/services/environments/job payload for a request.

        Shape consumed by the Step-1 Lambda worker:

        ``{app: {appId, appName}, services: [{svcId, svcName, serviceType}],
        environments: [...], job: {jobId, status}}``

        ``environments`` is derived from the distinct ``cluster.environment``
        of the request's services . Each capability also carries the cluster
        access for its environment (``kubeApiEndpoint``/``kubeToken``/
        ``kubeCaCert``, None when the cluster row has none) so the Step-2
        worker reaches the right cluster per capability. ``serviceType`` is
        emitted as the wire value (``fast-api``, ``node-js``, ``spring-boot``)
        so workers can map it directly to a golden-path template.

        ``requestType`` and ``rawRequest`` let a worker branch on the kind of
        reconciliation this run performs — e.g. a ``delete_app`` request tears
        its target environment down instead of applying it, and an
        ``update_app`` request whose entries carry removal lists deletes those
        XRs instead of upserting them.
        """
        request = self._get_request(request_id)
        app = self._resolve_app(request)
        job = self.jobRepository.get_by_request_id(request.requestId)

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

        # Capabilities are environment-scoped: resolved per-capability via the
        # services each capability grants access to. This gives the Step-2
        # (provision-infra / Crossplane) worker the desired config for each
        # capability, the namespace its instance must land in ({appName}-{env}),
        # and the *cluster* that instance belongs to — kubeApiEndpoint,
        # kubeToken, kubeCaCert come from the same Cluster row that resolves
        # the environment, so each env's workloads reach their own cluster.
        capabilities = []
        for cap in self.capabilityRepository.get_by_app(app.appId):
            accesses = self.capabilityAccessRepository.get_by_capability(cap.capabilityId)
            env_for_cap = None
            kube_endpoint = None
            kube_token = None
            kube_ca_cert = None
            service_names = []
            for access in accesses:
                svc = self.serviceRepository.get_by_id(access.serviceId)
                if svc is None:
                    continue
                service_names.append(svc.svcName)
                cluster = self.clusterRepository.get_by_id(svc.clusterId)
                if cluster is not None and env_for_cap is None:
                    env_for_cap = cluster.environment
                    kube_endpoint = cluster.kubeApiEndpoint
                    kube_token = cluster.kubeToken
                    kube_ca_cert = cluster.kubeCaCert

            infra = self.infraRequirementRepository.get_by_capability(cap.capabilityId)

            capabilities.append(
                {
                    "capabilityId": cap.capabilityId,
                    "capabilityType": cap.capabilityType,
                    "status": cap.status.value,
                    "config": infra.config if infra else None,
                    "environment": env_for_cap,
                    "namespace": f"{app.appName}-{env_for_cap}" if env_for_cap else None,
                    "kubeApiEndpoint": kube_endpoint,
                    "kubeToken": kube_token,
                    "kubeCaCert": kube_ca_cert,
                    "accessToServices": service_names,
                }
            )

        return {
            "requestType": request.requestType.value,
            "rawRequest": request.rawRequest or {},
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
            "capabilities": capabilities,
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
        if payload.gitOpsPath:
            app.gitOpsPath = payload.gitOpsPath

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

        self._apply_capability_outputs(request, payload.capabilities)

        # Teardown bookkeeping: the pipeline could still re-derive deterministic
        # XR names from live rows on any retry, so the desired-state rows a
        # delete owns are only removed once a run reports SUCCESS. Request/Job
        # rows survive as the audit trail.
        if status == JobStatus.SUCCESS:
            if request.requestType == RequestType.DELETE_APP:
                self._purge_env(app, (request.rawRequest or {}).get("env"))
            elif request.requestType == RequestType.UPDATE_APP:
                self._purge_removed_items(app, request.rawRequest or {})

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

    def record_deployment_setup(
        self,
        report: InternalDeploymentSetupReport,
    ) -> dict:
        """Persist a service's rollout state as reported by the deploy reporter.

        The ArgoCD/rollout reporter calls this with the sync/health outcome for
        a service. The service must exist (``svcId``), and reports are
        keyed to a ``serviceId`` via ``DeploymentSetupRepository.upsert`` so a
        retry reconciles instead of duplicating rows. ``status`` is persisted
        verbatim — the read side derives health from its meaning
        (``success`` → healthy, ``failed``/``errorMessage`` → unhealthy, else
        unknown), so unknown verbatim values keep the endpoint honest.

        All writes commit in one unit of work, matching the status callback.
        """
        svc = self.serviceRepository.get_by_id(report.svcId)
        if svc is None:
            raise NotFoundException(
                message=f"Service {report.svcId} not found.",
                error_code="SERVICE_NOT_FOUND",
            )

        values = {"status": report.status}
        if report.argocdAppName is not None:
            values["argocdAppName"] = report.argocdAppName
        if report.lastSyncedAt is not None:
            values["lastSyncedAt"] = report.lastSyncedAt
        if report.errorMessage is not None:
            values["errorMessage"] = report.errorMessage

        self.deploymentSetupRepository.upsert(report.svcId, values)
        self.session.commit()

        return {
            "message": "Deployment setup recorded.",
            "svcId": report.svcId,
            "status": report.status,
        }

    def list_deployment_group_services(self, app_name: str, env: str) -> dict:
        """Resolve the deployment group for one ``(app, env)`` ArgoCD instance.

        The ArgoCD ApplicationSet creates one Application per ``(app, env)``
        overlay, labeled ``app``/``environment``. The health reporter lists
        those Applications and needs the matching services to report against —
        this is that lookup: app must exist, then all services belonging to the
        app scoped to the cluster for ``env``. An env with no cluster yet
        returns an honest empty group (the reporter skips it).
        """
        app = self.appRepository.get_by_name(app_name)
        if app is None:
            raise NotFoundException(
                message=f"App '{app_name}' not found.",
                error_code="APP_NOT_FOUND",
            )

        cluster = self.clusterRepository.get_by_env(env)
        if cluster is None:
            return {"env": env, "svcIds": []}

        services = self.serviceRepository.get_by_app(app.appId, cluster_id=cluster.clusterId)
        return {"env": env, "svcIds": [svc.svcId for svc in services]}

    def get_cluster_details(self, cluster_name: str) -> dict:
        """Redacted cluster info for bootstrap/verification.

        Used by operators to confirm a cluster registration persisted the way
        they expect. Deliberately does **not** return the raw token/CA — only
        whether each is present, so the internal surface never leaks the
        credential back out.
        """
        cluster = self.clusterRepository.get_by_name(cluster_name)
        if cluster is None:
            raise NotFoundException(
                message=f"Cluster '{cluster_name}' not found.",
                error_code="CLUSTER_NOT_FOUND",
            )

        return {
            "clusterName": cluster.clusterName,
            "environment": cluster.environment,
            "kubeApiEndpoint": cluster.kubeApiEndpoint,
            "hasToken": cluster.kubeToken is not None,
            "hasCaCert": cluster.kubeCaCert is not None,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Teardown: desired-state purges (worker success callbacks)
    # ------------------------------------------------------------------ #

    def _purge_env(self, app: App, env: str | None) -> None:
        """Hard-delete every desired-state row an env-scoped delete owns.

        ``env`` is the rawRequest value the delete endpoint recorded; an
        unknown/absent one or an unregistered cluster purges nothing (the rows
        were never created for it anyway).
        """
        if not env:
            logger.warning("delete purge skipped: no env in rawRequest (app %s)", app.appId)
            return
        cluster = self.clusterRepository.get_by_env(env)
        if cluster is None:
            logger.warning("delete purge skipped: no cluster registered for env '%s'", env)
            return

        services = self.serviceRepository.get_by_app(
            app.appId, cluster_id=cluster.clusterId
        )
        cap_ids = [
            cap.capabilityId
            for cap in self.capabilityRepository.get_by_app(app.appId)
            if self._capability_env(cap) == env
        ]
        self._purge_rows(
            svc_ids=[svc.svcId for svc in services], cap_ids=cap_ids
        )
        logger.info(
            "purged environment '%s' for app %s (%d services, %d capabilities)",
            env,
            app.appName,
            len(services),
            len(cap_ids),
        )

    def _purge_removed_items(self, app: App, raw_request: dict) -> None:
        """Hard-delete the rows an update's removal lists named.

        Each ``updates`` entry may carry ``remove_services`` (base names) and
        ``remove_capabilities`` (capability-type values), validated by the
        update service at submit time; this is their post-success execution.
        """
        for entry in raw_request.get("updates") or []:
            env = entry.get("env")
            cluster = self.clusterRepository.get_by_env(env)
            if cluster is None:
                continue

            removed_services = set(entry.get("remove_services") or [])
            svc_ids = []
            for svc in self.serviceRepository.get_by_app(
                app.appId, cluster_id=cluster.clusterId
            ):
                base = (
                    svc.svcName.rsplit(f"-{env}", 1)[0]
                    if svc.svcName.endswith(f"-{env}") else svc.svcName
                )
                if base in removed_services:
                    svc_ids.append(svc.svcId)

            removed_caps = set(entry.get("remove_capabilities") or [])
            cap_ids = [
                cap.capabilityId
                for cap in self.capabilityRepository.get_by_app(app.appId)
                if cap.capabilityType in removed_caps
                and self._capability_env(cap) == env
            ]
            if svc_ids or cap_ids:
                self._purge_rows(svc_ids=svc_ids, cap_ids=cap_ids)
                logger.info(
                    "purged update removals for app %s in '%s' "
                    "(%d services, %d capabilities)",
                    app.appName,
                    env,
                    len(svc_ids),
                    len(cap_ids),
                )

    def _capability_env(self, cap: Capability) -> str | None:
        """The env a capability is scoped to, derived the same way
        ``get_request_details`` derives it: from the cluster of the services it
        grants access to."""
        for access in self.capabilityAccessRepository.get_by_capability(
            cap.capabilityId
        ):
            svc = self.serviceRepository.get_by_id(access.serviceId)
            if svc is None:
                continue
            cluster = self.clusterRepository.get_by_id(svc.clusterId)
            if cluster is not None:
                return cluster.environment
        return None

    def _purge_rows(self, svc_ids: list[int], cap_ids: list[int]) -> None:
        """Delete the rows a teardown owns, children first (FK order):
        deployment setups and access edges, then infra requirements and
        capabilities, then the services. Flushed rows commit with the caller's
        single ``session.commit()``."""
        for svc_id in svc_ids:
            self.deploymentSetupRepository.delete_all_by_service(svc_id)
            for access in self.capabilityAccessRepository.get_by_service(svc_id):
                self.capabilityAccessRepository.delete(access)
        for cap_id in cap_ids:
            for access in self.capabilityAccessRepository.get_by_capability(cap_id):
                self.capabilityAccessRepository.delete(access)
            infra = self.infraRequirementRepository.get_by_capability(cap_id)
            if infra is not None:
                self.infraRequirementRepository.delete(infra)
            cap = self.capabilityRepository.get_by_id(cap_id)
            if cap is not None:
                self.capabilityRepository.delete(cap)
        for svc_id in svc_ids:
            svc = self.serviceRepository.get_by_id(svc_id)
            if svc is not None:
                self.serviceRepository.delete(svc)

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
        """The app a request belongs to."""
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

    def _apply_capability_outputs(
        self,
        request: Request,
        capabilities: list[InternalCapabilityOutput] | None,
    ) -> None:
        """Persist the Step-2 (Crossplane) worker's per-capability results.

        For each reported capability:
          - validates it belongs to this request's app,
          - writes ``InfraRequirement.outputRef`` / ``secretRef``,
          - rolls ``Capability.status`` up to the reported per-capability status.
        """
        if not capabilities:
            return

        app = self._resolve_app(request)

        for report in capabilities:
            capability_id = report.capabilityId
            cap = self.capabilityRepository.get_by_id(capability_id)
            if cap is None:
                raise NotFoundException(
                    message=f"Capability {capability_id} not found.",
                    error_code="CAPABILITY_NOT_FOUND",
                )

            # Guard against a worker reporting a capability from another app.
            owned = self.capabilityRepository.get_by_app(app.appId)
            if all(c.capabilityId != capability_id for c in owned):
                raise BadRequestException(
                    message=f"Capability {capability_id} does not belong to request's app.",
                    error_code="CAPABILITY_NOT_IN_APP",
                )

            infra = self.infraRequirementRepository.get_by_capability(capability_id)
            if infra is None:
                raise NotFoundException(
                    message=f"No infra requirement for capability {capability_id}.",
                    error_code="INFRA_REQUIREMENT_NOT_FOUND",
                )

            if report.outputRef is not None:
                infra.outputRef = report.outputRef
            if report.secretRef is not None:
                infra.secretRef = report.secretRef
            if report.errorMessage is not None:
                infra.errorMessage = report.errorMessage
            infra.modifiedBy = "makeway-worker"

            cap.status = self._parse_capability_status(report.status)
            if report.errorMessage is not None:
                cap.errorMessage = report.errorMessage
            cap.modifiedBy = "makeway-worker"

    @staticmethod
    def _parse_capability_status(value: str) -> CapabilityStatus:
        try:
            return CapabilityStatus(value)
        except ValueError:
            raise BadRequestException(
                message=f"Unknown capability status '{value}'.",
                error_code="INVALID_CAPABILITY_STATUS",
            )

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