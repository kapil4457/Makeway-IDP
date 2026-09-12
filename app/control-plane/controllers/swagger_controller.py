from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

router = APIRouter(tags=["Documentation"])

SWAGGER_DIR = Path(__file__).parent.parent / "swagger"
SWAGGER_UI_PATH = SWAGGER_DIR / "swagger-ui.html"
MAKEWAY_LOGO_PATH = SWAGGER_DIR / "makeway-logo.svg"


@router.get("/docs", include_in_schema=False)
def get_swagger_ui() -> HTMLResponse:
    """Serve the Makeway-branded Swagger UI.

    The UI loads the OpenAPI schema that FastAPI generates from the code
    (`/openapi.json`), so the documentation can never drift from the models.
    """
    return HTMLResponse(
        SWAGGER_UI_PATH.read_text(encoding="utf-8"),
        # Branding lives in this file — never let a browser pin a stale copy.
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/swagger/logo.svg", include_in_schema=False)
def get_makeway_logo() -> FileResponse:
    """The Makeway brand mark (same asset as the frontend favicon)."""
    return FileResponse(
        MAKEWAY_LOGO_PATH,
        media_type="image/svg+xml",
        # no-cache = revalidate before reuse, so logo updates propagate
        # instead of a browser serving its cached copy for days.
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/swagger/docs", include_in_schema=False)
def get_swagger_ui_legacy() -> RedirectResponse:
    """Backward-compatible redirect for the old docs URL."""
    return RedirectResponse(url="/docs", status_code=308)


@router.get("/swagger/openapi.json", include_in_schema=False)
def get_openapi_legacy() -> RedirectResponse:
    """Backward-compatible redirect for the old static schema URL."""
    return RedirectResponse(url="/openapi.json", status_code=308)
