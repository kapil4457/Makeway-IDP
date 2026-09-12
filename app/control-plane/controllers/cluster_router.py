from fastapi import APIRouter, Depends

from core import get_logger
from dto.response.register_cluster import ClusterRegisterResponse
from dto.response.cluster_summary import ClusterSummaryResponse
from dto.request.register_cluster import ClusterRegisterRequest
from service.cluster_service import ClusterService
from dependencies.cluster import get_cluster_service
from database.models.user import User
from dependencies.auth import get_current_user


logger = get_logger(__name__)

router = APIRouter(prefix="/cluster", tags=["Cluster Management"])


@router.get(
    "",
    summary="List registered clusters",
    description=(
        "Lists every cluster registered with the platform, most recently "
        "modified first. Worker credentials are never returned — only "
        "``hasToken``/``hasCaCert`` presence flags, mirroring the redacted "
        "internal verification surface."
    ),
    response_model=list[ClusterSummaryResponse],
    response_description="The platform's registered clusters, credentials redacted.",
)
def list_clusters(
    current_user: User = Depends(get_current_user),
    cluster_service: ClusterService = Depends(get_cluster_service),
) -> list[ClusterSummaryResponse]:
    logger.info(
        "Cluster list requested",
        extra={
            "extra_fields": {
                "user_id": getattr(current_user, "userId", None),
            }
        },
    )
    return cluster_service.list_clusters()


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

