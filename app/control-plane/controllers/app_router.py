from fastapi import APIRouter, Header, Depends, status

from core import get_logger
from dto.configs.app_config import AppConfig
from dto.response.create_app import AppCreateResponse
from dto.response.app_status import AppStatusResponse
from database.models.user import User
from dependencies.auth import get_current_user
from service.app_creation_service import AppCreationService
from service.app_status_service import AppStatusService
from dependencies.app import get_app_creation_service, get_app_status_service


logger = get_logger(__name__)

router = APIRouter(prefix="/app", tags=["App Management"])


@router.post(
    "/create",
    summary="Create a new app",
    description=(
        "Registers the desired state for a new application. Makeway reconciles the "
        "requested capabilities (services, database, storage, messaging) into real "
        "infrastructure asynchronously. The operation is "
        "idempotent” retrying with the same payload never duplicates resources."
    ),
    response_model=AppCreateResponse,
    response_description="The app creation request was accepted.",
)
def create_app(app_config: AppConfig, 
               idempotency_key: str = Header( ...,
                    alias="Idempotency-Key",
                    min_length=8,
                    max_length=255
                    ),
                current_user: User = Depends(get_current_user),
                service: AppCreationService = Depends(
                    get_app_creation_service
                    ),

               ) -> AppCreateResponse:
    logger.info(
        "App creation requested",
        extra={
            "extra_fields": {
                "app_name": app_config.app_name,
                "environments": [env_cfg.env.value for env_cfg in app_config.env_config],
            }
        },
    )
    return service.submit(
        app_config=app_config,
        user=current_user,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{app_name}/status",
    summary="Get an app's per-environment status",
    description=(
        "Returns a per-environment snapshot of an app: the services in each "
        "env, the capabilities bound to them, the connectivity edges in "
        "between, and any errors at each level. Status fields carry a "
        "``dataSource`` marker — ``persisted`` means last-known reconcile "
        "state, ``realtime`` means a live cluster/ArgoCD check filled the "
        "value. Health is ``unknown`` until a reporter records a real value. "
        "Only the app's owning team may view it."
    ),
    response_model=AppStatusResponse,
    response_description="The app's current per-environment status snapshot.",
)
def get_app_status(
    app_name: str,
    current_user: User = Depends(get_current_user),
    service: AppStatusService = Depends(get_app_status_service),
) -> AppStatusResponse:
    logger.info(
        "App status requested",
        extra={
            "extra_fields": {
                "app_name": app_name,
                "user_id": getattr(current_user, "userId", None),
            }
        },
    )
    return service.get_app_status(
        app_name=app_name,
        current_user=current_user,
    )