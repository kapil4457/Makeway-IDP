from fastapi import APIRouter, Depends

from core import get_logger
from dto.response.register_cluster import ClusterRegisterResponse
from dto.request.register_cluster import ClusterRegisterRequest
from service.cluster_service import ClusterService
from dependencies.cluster import get_cluster_service
from database.models.user import User
from dependencies.auth import get_current_user


logger = get_logger(__name__)

router = APIRouter(prefix="/cluster", tags=["Cluster Management"])


@router.post(
    "/register",
    summary="Register a new cluster",
    description=("Registers the desired state for a new cluster."),
    response_model=ClusterRegisterResponse,
    response_description="The cluster registration request was accepted.",
)
def register_cluster(cluster_config: ClusterRegisterRequest, 
                     cluster_service: ClusterService = Depends(get_cluster_service),
                     current_user: User = Depends(get_current_user),

                     ) -> ClusterRegisterResponse:
    logger.info(
        "Cluster registration requested",
        extra={
            "extra_fields": {
                "cluster_name": cluster_config.clusterName,
                "kube_api_endpoint": cluster_config.kubeApiEndpoint,
            }
        },
    )

    return cluster_service.register_cluster(request=cluster_config,current_user=current_user)

