from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["Documentation"])

SWAGGER_UI_PATH = Path(__file__).parent.parent / "swagger" / "swagger-ui.html"


@router.get("/docs", include_in_schema=False)
def get_swagger_ui() -> HTMLResponse:
    """Serve the Makeway-branded Swagger UI.

    The UI loads the OpenAPI schema that FastAPI generates from the code
    (`/openapi.json`), so the documentation can never drift from the models.
    """
    return HTMLResponse(SWAGGER_UI_PATH.read_text(encoding="utf-8"))


@router.get("/swagger/docs", include_in_schema=False)
def get_swagger_ui_legacy() -> RedirectResponse:
    """Backward-compatible redirect for the old docs URL."""
    return RedirectResponse(url="/docs", status_code=308)


@router.get("/swagger/openapi.json", include_in_schema=False)
def get_openapi_legacy() -> RedirectResponse:
    """Backward-compatible redirect for the old static schema URL."""
    return RedirectResponse(url="/openapi.json", status_code=308)
