from fastapi import APIRouter, Header, Depends, status

from core import get_logger
from dto.configs.app_config import AppConfig
from dto.response.create_app import AppCreateResponse
from database.models.user import User
from dependencies.auth import get_current_user
from service.app_creation_service import AppCreationService
from dependencies.app import get_app_creation_service


logger = get_logger(__name__)

router = APIRouter(prefix="/app", tags=["App Management"])


@router.post(
    "/create",
    summary="Create a new app",
    description=(
        "Registers the desired state for a new application. Makeway reconciles the "
        "requested capabilities (services, database, storage, observability, "
        "messaging) into real infrastructure asynchronously. The operation is "
        "idempotent â€” retrying with the same payload never duplicates resources."
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

