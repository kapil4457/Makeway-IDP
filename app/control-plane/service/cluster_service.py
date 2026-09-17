from dto.response.register_cluster import ClusterRegisterResponse
from dto.response.cluster_summary import ClusterSummaryResponse
from dto.response.delete_cluster import ClusterDeleteResponse
from dto.request.register_cluster import ClusterRegisterRequest
from dto.request.update_cluster import ClusterUpdateRequest
from repository.cluster_repository import ClusterRepository
from repository.service_repository import ServiceRepository
from database.models.user import User
from database.models.cluster import Cluster
from exceptions.base import ConflictException, NotFoundException


class ClusterService:

    def __init__(self, repository: ClusterRepository, serviceRepository: ServiceRepository):
        self.repository = repository
        self.serviceRepository = serviceRepository

    def list_clusters(self) -> list[ClusterSummaryResponse]:
        """All registered clusters, credential values redacted to presence flags."""
        return [self._summary(cluster) for cluster in self.repository.list_all()]

    def _summary(self, cluster: Cluster) -> ClusterSummaryResponse:
        return ClusterSummaryResponse(
            clusterId=cluster.clusterId,
            clusterName=cluster.clusterName,
            kubeApiEndpoint=cluster.kubeApiEndpoint,
            environment=cluster.environment,
            hasToken=bool(cluster.kubeToken),
            hasCaCert=bool(cluster.kubeCaCert),
            createdBy=cluster.createdBy,
            createdAt=cluster.createdAt,
            modifiedBy=cluster.modifiedBy,
            modifiedAt=cluster.modifiedAt,
        )

    def update_cluster(
        self,
        cluster_id: int,
        request: ClusterUpdateRequest,
        current_user: User,
    ) -> ClusterSummaryResponse:
        """Patch a registered cluster in place.

        Omitted fields keep their stored value (token/CA follow register's
        never-wipe rule); ``environment`` is not patchable — it is the
        routing key for app creation, and moving a cluster silently would
        re-route every app that resolves its env through ``get_by_env``.
        Delete-and-re-register is the supported way to change an environment.
        """
        cluster = self.repository.get_by_id(cluster_id)
        if cluster is None:
            raise NotFoundException(
                message=f"Cluster {cluster_id} not found.",
                error_code="CLUSTER_NOT_FOUND",
            )

        if request.clusterName and request.clusterName != cluster.clusterName:
            occupant = self.repository.get_by_name(request.clusterName)
            if occupant is not None and occupant.clusterId != cluster.clusterId:
                raise ConflictException(
                    message=f"A cluster named '{request.clusterName}' already "
                            f"exists (environment '{occupant.environment}').",
                    error_code="CLUSTER_NAME_CONFLICT",
                )
            cluster.clusterName = request.clusterName

        if request.kubeApiEndpoint is not None:
            cluster.kubeApiEndpoint = str(request.kubeApiEndpoint)
        if request.kubeToken is not None:
            cluster.kubeToken = request.kubeToken
        if request.kubeCaCert is not None:
            cluster.kubeCaCert = request.kubeCaCert

        cluster.modifiedBy = current_user.email
        cluster = self.repository.create(cluster)

        return self._summary(cluster)

    def delete_cluster(
        self,
        cluster_id: int,
        current_user: User,
    ) -> ClusterDeleteResponse:
        """Deregister a cluster, freeing its environment for re-registration.

        Refused while any service row still deploys to it: services hold a
        NOT NULL FK to the cluster, and an app targeting that environment
        would silently route into the void. Tear the apps' environments down
        first — the register flow's one-cluster-per-env rule then governs the
        replacement.
        """
        cluster = self.repository.get_by_id(cluster_id)
        if cluster is None:
            raise NotFoundException(
                message=f"Cluster {cluster_id} not found.",
                error_code="CLUSTER_NOT_FOUND",
            )

        services = self.serviceRepository.get_by_cluster(cluster_id)
        if services:
            raise ConflictException(
                message=(
                    f"Cluster '{cluster.clusterName}' still serves "
                    f"{len(services)} service row(s). Delete the apps' "
                    f"environments on it first."
                ),
                error_code="CLUSTER_IN_USE",
            )

        # Capture before the delete commits: attribute access on a committed,
        # deleted instance would trigger a refresh that finds nothing.
        response = ClusterDeleteResponse(
            clusterName=cluster.clusterName,
            environment=cluster.environment,
        )
        self.repository.delete(cluster)

        return response

    def register_cluster(self, request: ClusterRegisterRequest,current_user:User) -> ClusterRegisterResponse:
        """
        Registers (or refreshes) a cluster with the provided configuration.

        Idempotent by ``clusterName``: re-registering the same name on the same
        environment refreshes ``kubeApiEndpoint`` and any provided
        token/CA (which is how a tunnel endpoint change after a restart
        is applied). Re-registering the same name on a *different* environment
        is rejected — the environment is the routing key and a cluster must not
        silently move. A ``None`` token/CA on refresh leaves the persisted value
        untouched, so a token-less refresh never wipes a stored credential.

        Args:
            request (ClusterRegisterRequest): The configuration for the cluster to be registered.

        Returns:
            ClusterRegisterResponse: A response indicating the result of the registration request.
        """


        existing = self.repository.get_by_name(
            request.clusterName
        )

        if existing:
            if existing.environment != request.environment.value:
                raise ConflictException(
                    message="A cluster with this name already exists on a different environment.",
                    error_code="CLUSTER_ENVIRONMENT_MISMATCH",
                )
            existing.kubeApiEndpoint = str(request.kubeApiEndpoint)
            if request.kubeToken is not None:
                existing.kubeToken = request.kubeToken
            if request.kubeCaCert is not None:
                existing.kubeCaCert = request.kubeCaCert
            existing.modifiedBy = current_user.email

            cluster = self.repository.create(existing)
            return ClusterRegisterResponse(
                message="Cluster registration updated",
                cluster_name=cluster.clusterName,
            )

        # One cluster per environment: app creation resolves clusters by env
        # (get_by_env), so a second row for the same env would make that
        # resolution ambiguous. Re-registering the occupying cluster BY NAME
        # is the supported refresh path and never reaches this branch.
        occupant = self.repository.get_by_env(request.environment.value)
        if occupant is not None:
            raise ConflictException(
                message=f"Environment '{request.environment.value}' is already "
                        f"served by cluster '{occupant.clusterName}'. "
                        f"Re-register '{occupant.clusterName}' by name to "
                        f"refresh it.",
                error_code="CLUSTER_ENVIRONMENT_CONFLICT",
            )

        cluster = Cluster(
            clusterName=request.clusterName,
            kubeApiEndpoint=str(request.kubeApiEndpoint),
            environment=request.environment.value,
            kubeToken=request.kubeToken,
            kubeCaCert=request.kubeCaCert,
            createdBy=current_user.email,
            modifiedBy=current_user.email
        )

        cluster = self.repository.create(cluster)

        return ClusterRegisterResponse(
            message="Cluster registration requested",
            cluster_name=cluster.clusterName,
        )