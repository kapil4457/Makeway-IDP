import uuid
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from database.db_engine import  dispose_engine

from controllers.app_router import router as app_router
from controllers.cluster_router import router as cluster_router
from controllers.swagger_controller import router as swagger_router
from controllers.auth_router import router as auth_router
from controllers.internal_router import router as internal_router
from auth.interceptor import AuthInterceptor
from core.logger import get_logger, set_request_id, setup_logging
from core.exception_handlers import register_exception_handlers

load_dotenv()
logger = get_logger(__name__)

API_DESCRIPTION = """
Makeway is an AI-Assisted Internal Developer Platform (IDP).

Use this API to onboard applications onto the platform: declare the desired
state (services, databases, storage, messaging) and Makeway reconciles it
into real infrastructure through Terraform, GitOps, and Vault.

### Conventions

* All provisioning operations are **idempotent** â€” retries never create
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
    {
        "name": "User Management",
        "description": "Manage users, teams, and access control for applications."
    },
    {
        "name": "Cluster Management",
        "description": "Manage clusters and their configurations."
    }
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Makeway starting up")

    yield

    logger.info("Makeway shutting down")
    dispose_engine()


app = FastAPI(
    title="Makeway API",
    version="0.1.0",
    summary="",
    description=API_DESCRIPTION,
    contact={"name": "Makeway Platform Team"},
    openapi_tags=API_TAGS,
    # The branded Swagger UI is served by swagger_controller at /docs.
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(
    AuthInterceptor,
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(app_router)
app.include_router(cluster_router)
app.include_router(auth_router)
app.include_router(swagger_router)
app.include_router(internal_router)
