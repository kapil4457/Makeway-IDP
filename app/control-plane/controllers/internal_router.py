"""Internal endpoints consumed by the app-creation state-machine workers.

Not part of the user-facing API surface; every route is guarded by the
``X-Internal-API-Key`` header (see ``dependencies.internal``). The Step-1
Lambda worker calls:

- ``GET /internal/requests/{request_id}`` — request snapshot (app, services,
  environments, job) before doing work.
- ``POST /internal/requests/{request_id}/status`` — report the outcome and the
  repo URLs / per-service folder paths it produced.
"""
from fastapi import APIRouter, Depends

from dependencies.internal import (
    get_internal_api_service,
    require_internal_api_key,
)
from dto.request.internal import InternalStatusUpdateRequest
from service.internal_api_service import InternalApiService


router = APIRouter(
    prefix="/internal",
    tags=["Internal State-Machine API"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.get(
    "/requests/{request_id}",
    summary="Get a request snapshot for a worker",
    description=(
        "Returns the app, services, environments, and job for a request so a "
        "state-machine step can execute against the desired state."
    ),
)
def get_request_details(
    request_id: int,
    service: InternalApiService = Depends(get_internal_api_service),
) -> dict:
    return service.get_request_details(request_id)


@router.post(
    "/requests/{request_id}/status",
    summary="Report a worker's outcome back",
    description=(
        "Applies a step's status, app repo URLs, and per-service folder paths, "
        "then rolls the request status up from the job status."
    ),
)
def update_request_status(
    request_id: int,
    payload: InternalStatusUpdateRequest,
    service: InternalApiService = Depends(get_internal_api_service),
) -> dict:
    return service.update_request_status(request_id, payload)