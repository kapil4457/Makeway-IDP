import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from exceptions.base import AppException


logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:


    @app.exception_handler(AppException)
    async def handle_app_exception(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
        )


    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:

        errors = []

        for error in exc.errors():
            location = error.get("loc", [])

            field = ".".join(str(item) for item in location)

            errors.append(
                {
                    "field": field,
                    "message": error.get("msg", "Invalid value."),
                    "code": error.get("type", "VALIDATION_ERROR"),
                }
            )

        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request contains invalid data.",
                    "details": errors,
                },
            },
        )



    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": "HTTP_ERROR",
                    "message": str(exc.detail),
                    "details": [],
                },
            },
        )


    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(
        request: Request,
        exc: IntegrityError,
    ) -> JSONResponse:

        logger.warning(
            "Database integrity error: %s",
            exc,
        )

        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "error": {
                    "code": "DATABASE_CONSTRAINT_VIOLATION",
                    "message": "The requested operation violates a database constraint.",
                    "details": [],
                },
            },
        )


    @app.exception_handler(OperationalError)
    async def handle_operational_error(
        request: Request,
        exc: OperationalError,
    ) -> JSONResponse:

        logger.exception(
            "Database operational error",
            exc_info=exc,
        )

        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "The database is temporarily unavailable.",
                    "details": [],
                },
            },
        )


    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy_error(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:

        logger.exception(
            "Unhandled database error",
            exc_info=exc,
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "DATABASE_ERROR",
                    "message": "A database error occurred.",
                    "details": [],
                },
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:

        logger.exception(
            "Unhandled application exception",
            exc_info=exc,
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred.",
                    "details": [],
                },
            },
        )