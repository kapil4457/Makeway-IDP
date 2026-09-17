from fastapi import APIRouter, Depends

from core import get_logger
from dto.response.register_cluster import ClusterRegisterResponse
from dto.response.cluster_summary import ClusterSummaryResponse
from dto.response.delete_cluster import ClusterDeleteResponse
from dto.request.register_cluster import ClusterRegisterRequest
from dto.request.update_cluster import ClusterUpdateRequest
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



@router.put(
    "/{cluster_id}",
    summary="Update a registered cluster",
    description=(
        "Patches a registered cluster in place: rename it, point its "
        "``kubeApiEndpoint`` at a replacement (e.g. after a tunnel endpoint "
        "changes), or rotate the worker token/CA. Omitted fields keep their "
        "stored value; the token/CA follow the register contract — ``None`` "
        "never wipes a stored credential, and clearing a credential is not "
        "supported here. The environment is deliberately not patchable: it "
        "is the routing key app creation resolves clusters by, so moving a "
        "cluster to another environment means delete-and-re-register."
    ),
    response_model=ClusterSummaryResponse,
    response_description="The updated cluster, credentials redacted.",
)
def update_cluster(
    cluster_id: int,
    update: ClusterUpdateRequest,
    current_user: User = Depends(get_current_user),
    cluster_service: ClusterService = Depends(get_cluster_service),
) -> ClusterSummaryResponse:
    logger.info(
        "Cluster update requested",
        extra={
            "extra_fields": {
                "cluster_id": cluster_id,
                "user_id": getattr(current_user, "userId", None),
            }
        },
    )
    return cluster_service.update_cluster(
        cluster_id=cluster_id,
        request=update,
        current_user=current_user,
    )


@router.delete(
    "/{cluster_id}",
    summary="Deregister a cluster",
    description=(
        "Hard-deletes a registered cluster, freeing its environment for "
        "re-registration. Refused while any service row still deploys to it "
        "— delete the apps' environments on that cluster first, since an app "
        "targeting this environment would otherwise silently route into the "
        "void. Credentials stored for the cluster are removed with the row."
    ),
    response_model=ClusterDeleteResponse,
    response_description="The cluster was deregistered.",
)
def delete_cluster(
    cluster_id: int,
    current_user: User = Depends(get_current_user),
    cluster_service: ClusterService = Depends(get_cluster_service),
) -> ClusterDeleteResponse:
    logger.info(
        "Cluster deregistration requested",
        extra={
            "extra_fields": {
                "cluster_id": cluster_id,
                "user_id": getattr(current_user, "userId", None),
            }
        },
    )
    return cluster_service.delete_cluster(
        cluster_id=cluster_id,
        current_user=current_user,
    )
