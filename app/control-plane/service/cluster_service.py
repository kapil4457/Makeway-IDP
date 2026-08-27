from dto.response.register_cluster import ClusterRegisterResponse
from dto.request.register_cluster import ClusterRegisterRequest
from repository.cluster_repository import ClusterRepository
from database.models.user import User
from exceptions.base import ConflictException
from database.models.cluster import Cluster


class ClusterService:

    def __init__(self, repository: ClusterRepository):
        self.repository = repository

    def register_cluster(self, request: ClusterRegisterRequest,current_user:User) -> ClusterRegisterResponse:
        """
        Registers a new cluster with the provided configuration.

        Args:
            cluster_config (ClusterRegisterRequest): The configuration for the cluster to be registered.

        Returns:
            ClusterRegisterResponse: A response indicating the result of the registration request.
        """


        existing = self.repository.get_by_name(
            request.clusterName
        )

        if existing:
            raise ConflictException(
                message="A cluster with this name already exists.",
                error_code="CLUSTER_ALREADY_EXISTS",
            )

        cluster = Cluster(
            clusterName=request.clusterName,
            kubeApiEndpoint=str(request.kubeApiEndpoint),
            environment=request.environment.value,
            createdBy=current_user.email,
            modifiedBy=current_user.email
        )

        cluster = self.repository.create(cluster)
        
        return ClusterRegisterResponse(
            message="Cluster registration requested",
            cluster_name=cluster.clusterName,
        )