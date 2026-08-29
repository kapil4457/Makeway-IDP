"""Dependencies for the internal (state-machine worker) API.

The ``X-Internal-API-Key`` guard lives here instead of the public auth
middleware: ``AuthInterceptor`` deliberately passes requests through when no
``Authorization`` header is present, so worker callbacks (which authenticate
with the internal key alone) must be checked inside these routes.
"""
import hmac
import os

from fastapi import Depends, Header
from sqlmodel import Session

from dependencies.database import get_database_session
from exceptions.base import UnauthorizedException
from repository.app_repository import AppRepository
from repository.cluster_repository import ClusterRepository
from repository.job_repository import JobRepository
from repository.request_repository import RequestRepository
from repository.service_repository import ServiceRepository
from service.internal_api_service import InternalApiService

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")


def require_internal_api_key(
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-API-Key"),
) -> None:
    """Fail-closed guard: no configured key, or a mismatch, rejects the call."""
    if not INTERNAL_API_KEY:
        raise UnauthorizedException(
            message="Internal API is not configured (INTERNAL_API_KEY is unset).",
            error_code="INTERNAL_API_MISCONFIGURED",
        )
    if x_internal_api_key is None or not hmac.compare_digest(
        INTERNAL_API_KEY, x_internal_api_key
    ):
        raise UnauthorizedException(
            message="Invalid internal API key.",
            error_code="INVALID_INTERNAL_API_KEY",
        )


def get_internal_api_service(
    session: Session = Depends(get_database_session),
) -> InternalApiService:

    return InternalApiService(
        session=session,
        requestRepository=RequestRepository(session),
        jobRepository=JobRepository(session),
        appRepository=AppRepository(session),
        serviceRepository=ServiceRepository(session),
        clusterRepository=ClusterRepository(session),
    )