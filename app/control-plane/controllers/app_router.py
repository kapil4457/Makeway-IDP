from fastapi import APIRouter, Header, Depends, status

from core import get_logger
from dto.configs.app_config import AppConfig
from dto.configs.env_config import EnvConfig
from dto.response.create_app import AppCreateResponse
from dto.response.app_purge import AppPurgeResponse
from dto.response.app_status import AppStatusResponse
from dto.response.app_summary import AppSummaryResponse
from database.models.user import User
from dependencies.auth import get_current_user
from dto.enums.environment import Environment
from service.app_creation_service import AppCreationService
from service.app_list_service import AppListService
from service.app_status_service import AppStatusService
from service.app_update_service import AppUpdateService
from service.app_delete_service import AppDeleteService
from dependencies.app import (
    get_app_creation_service,
    get_app_list_service,
    get_app_status_service,
    get_app_update_service,
    get_app_delete_service,
)


logger = get_logger(__name__)

router = APIRouter(prefix="/app", tags=["App Management"])


@router.get(
    "",
    summary="List apps visible to the current user",
    description=(
        "Lists the apps owned by the teams the current user is an active "
        "member of, most recently modified first. Read-only companion to "
        "``GET /app/{app_name}/status`` — the dashboard grid's data source."
    ),
    response_model=list[AppSummaryResponse],
    response_description="The caller's team-scoped app summaries.",
)
def list_apps(
    current_user: User = Depends(get_current_user),
    service: AppListService = Depends(get_app_list_service),
) -> list[AppSummaryResponse]:
    logger.info(
        "App list requested",
        extra={
            "extra_fields": {
                "user_id": getattr(current_user, "userId", None),
            }
        },
    )
    return service.list_apps(current_user=current_user)


@router.post(
    "/create",
    summary="Create a new app",
    description=(
        "Registers the desired state for a new application. Makeway reconciles the "
        "requested capabilities (services, database, storage, messaging) into real "
        "infrastructure asynchronously. The operation is "
        "idempotent — retrying with the same payload never duplicates resources."
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


@router.post(
    "/{app_name}/update",
    summary="Update an existing app",
    description=(
        "Submits a per-environment delta for an existing app: a JSON list of "
        "``{env, services?, capabilities?, remove_services?, "
        "remove_capabilities?}`` entries. Each entry states the desired state "
        "for the capabilities/services it mentions — a capability already "
        "provisioned for that environment gets its config updated (e.g. a "
        "larger database capacity tier), a new one is provisioned, a new "
        "service is scaffolded and rolled out. Anything not mentioned stays "
        "untouched. ``remove_services``/``remove_capabilities`` tear that item "
        "down for the environment (removing a service that is a capability's "
        "last accessor is rejected — name the capability for removal too, or "
        "keep another accessor). Removals in ``prod`` require ``confirm=true``. "
        "The operation is idempotent: retrying with the same Idempotency-Key "
        "returns the original request/job identifiers. Rejected while another "
        "request for the app is still reconciling."
    ),
    response_model=AppCreateResponse,
    response_description="The app update request was accepted.",
)
def update_app(
    app_name: str,
    updates: list[EnvConfig],
    confirm: bool = False,
    idempotency_key: str = Header( ...,
        alias="Idempotency-Key",
        min_length=8,
        max_length=255
        ),
    current_user: User = Depends(get_current_user),
    service: AppUpdateService = Depends(
        get_app_update_service
        ),

   ) -> AppCreateResponse:
    logger.info(
        "App update requested",
        extra={
            "extra_fields": {
                "app_name": app_name,
                "environments": [update.env.value for update in updates],
            }
        },
    )
    return service.submit(
        app_name=app_name,
        updates=updates,
        user=current_user,
        idempotency_key=idempotency_key,
        confirm=confirm,
    )


@router.delete(
    "/{app_name}/envs/{env}",
    summary="Delete an app's environment",
    description=(
        "Tears down everything an app runs in one environment: its services, "
        "the capabilities bound to them, their provisioned infrastructure "
        "(Crossplane tears the AWS resources down), and the environment's "
        "GitOps overlay. The desired-state rows are purged once the pipeline "
        "reports SUCCESS — until then a failed run reconciles instead of "
        "losing its teardown targets. If this is the app's last remaining "
        "environment, its entire GitOps tree is removed but the app record and "
        "services repository stay. Deleting ``prod`` requires ``confirm=true``."
        " The operation is idempotent: retrying with the same Idempotency-Key "
        "returns the original request/job identifiers. Rejected while another "
        "request for the app is still reconciling."
    ),
    response_model=AppCreateResponse,
    response_description="The app environment delete request was accepted.",
)
def delete_app_env(
    app_name: str,
    env: Environment,
    confirm: bool = False,
    idempotency_key: str = Header( ...,
        alias="Idempotency-Key",
        min_length=8,
        max_length=255
        ),
    current_user: User = Depends(get_current_user),
    service: AppDeleteService = Depends(
        get_app_delete_service
        ),

   ) -> AppCreateResponse:
    logger.info(
        "App environment delete requested",
        extra={
            "extra_fields": {
                "app_name": app_name,
                "environment": env.value,
            }
        },
    )
    return service.submit(
        app_name=app_name,
        env=env,
        user=current_user,
        idempotency_key=idempotency_key,
        confirm=confirm,
    )


@router.delete(
    "/{app_name}",
    summary="Purge an app's record",
    description=(
        "Hard-deletes the app row and its audit trail (requests, jobs) once "
        "every environment is gone. This is the recovery exit for the "
        "terminal state an app reaches after all its environments are torn "
        "down: the app can then be re-created under the same name. Only the "
        "record is removed — the services repository on GitHub stays, and any "
        "app that still has service rows in its desired state is rejected "
        "(use the environment delete instead). Rejected while another request "
        "for the app is still reconciling. Destructive and synchronous: "
        "requires ``confirm=true``."
    ),
    response_model=AppPurgeResponse,
    response_description="The app record was purged.",
)
def delete_app(
    app_name: str,
    confirm: bool = False,
    current_user: User = Depends(get_current_user),
    service: AppDeleteService = Depends(
        get_app_delete_service
        ),

   ) -> AppPurgeResponse:
    logger.info(
        "App record purge requested",
        extra={
            "extra_fields": {
                "app_name": app_name,
            }
        },
    )
    return service.purge_app(
        app_name=app_name,
        user=current_user,
        confirm=confirm,
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