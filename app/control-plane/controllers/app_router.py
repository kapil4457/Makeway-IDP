from fastapi import APIRouter

from core import get_logger
from dto.configs.app_config import AppConfig
from dto.response.create_app import AppCreateResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/app", tags=["App Management"])


@router.post(
    "/create",
    summary="Create a new app",
    description=(
        "Registers the desired state for a new application. Makeway reconciles the "
        "requested capabilities (services, database, cache, storage, observability, "
        "messaging) into real infrastructure asynchronously. The operation is "
        "idempotent — retrying with the same payload never duplicates resources."
    ),
    response_model=AppCreateResponse,
    response_description="The app creation request was accepted.",
)
def create_app(app_config: AppConfig) -> AppCreateResponse:
    logger.info(
        "App creation requested",
        extra={
            "extra_fields": {
                "app_name": app_config.app_name,
                "environments": [env_cfg.env.value for env_cfg in app_config.env_config],
            }
        },
    )

    return AppCreateResponse(
        message="App creation requested",
        app_name=app_config.app_name,
    )