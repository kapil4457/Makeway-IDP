from fastapi import FastAPI, Request
from fastapi.concurrency import asynccontextmanager

from controllers.app_router import router as app_router
from controllers.swagger_controller import router as swagger_router
from core.logger import get_logger, set_request_id, setup_logging

logger = get_logger(__name__)

API_DESCRIPTION = """
Makeway is an AI-Assisted Internal Developer Platform (IDP).

Use this API to onboard applications onto the platform: declare the desired
state (services, databases, caches, storage, observability, messaging) and
Makeway reconciles it into real infrastructure through Terraform, GitOps,
and Vault.

### Conventions

* All provisioning operations are **idempotent** — retries never create
  duplicate resources.
* Desired state is the source of truth; workers reconcile it into actual
  infrastructure.
* Dev/staging changes below the risk threshold auto-apply; production and
  destructive changes require explicit sign-off.
"""

API_TAGS = [
    {
        "name": "App Management",
        "description": "Onboard and manage applications on the Makeway platform.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Makeway starting up")
    yield
    logger.info("Makeway shutting down")


app = FastAPI(
    title="Makeway API",
    version="0.1.0",
    summary="AI-Assisted Internal Developer Platform",
    description=API_DESCRIPTION,
    contact={"name": "Makeway Platform Team"},
    openapi_tags=API_TAGS,
    # The branded Swagger UI is served by swagger_controller at /docs.
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", None)
    if request_id:
        set_request_id(request_id)
    response = await call_next(request)
    return response


app.include_router(app_router)
app.include_router(swagger_router)
