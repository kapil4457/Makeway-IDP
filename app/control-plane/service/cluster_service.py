from dto.response.register_cluster import ClusterRegisterResponse
from dto.response.cluster_summary import ClusterSummaryResponse
from dto.request.register_cluster import ClusterRegisterRequest
from repository.cluster_repository import ClusterRepository
from database.models.user import User
from exceptions.base import ConflictException
from database.models.cluster import Cluster


class ClusterService:

    def __init__(self, repository: ClusterRepository):
        self.repository = repository

    def list_clusters(self) -> list[ClusterSummaryResponse]:
        """All registered clusters, credential values redacted to presence flags."""
        clusters = self.repository.list_all()

        return [
            ClusterSummaryResponse(
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
            for cluster in clusters
        ]

    def register_cluster(self, request: ClusterRegisterRequest,current_user:User) -> ClusterRegisterResponse:
        """
        Registers (or refreshes) a cluster with the provided configuration.

        Idempotent by ``clusterName``: re-registering the same name on the same
        environment refreshes ``kubeApiEndpoint`` and any provided
        token/CA (which is how a pinggy endpoint change after a tunnel restart
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