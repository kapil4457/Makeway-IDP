from typing import Any


class AppException(Exception):
    """
    Base exception for all application-specific exceptions.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: list[dict[str, Any]] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or []

        super().__init__(message)


class BadRequestException(AppException):
    def __init__(
        self,
        message: str = "Bad request.",
        error_code: str = "BAD_REQUEST",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            error_code=error_code,
            details=details,
        )



class InvalidRequestException(BadRequestException):
    def __init__(
        self,
        errors: list[dict[str, Any]] | None = None,
        message: str = "The request contains invalid data.",
    ):
        super().__init__(
            message=message,
            error_code="INVALID_REQUEST",
            details=errors,
        )


class UnauthorizedException(AppException):
    def __init__(
        self,
        message: str = "Authentication is required.",
        error_code: str = "UNAUTHORIZED",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=401,
            error_code=error_code,
            details=details,
        )


class ForbiddenException(AppException):
    def __init__(
        self,
        message: str = "You do not have permission to perform this operation.",
        error_code: str = "FORBIDDEN",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=error_code,
            details=details,
        )


class NotFoundException(AppException):
    def __init__(
        self,
        message: str = "Resource not found.",
        error_code: str = "NOT_FOUND",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=404,
            error_code=error_code,
            details=details,
        )


class ConflictException(AppException):
    def __init__(
        self,
        message: str = "The request conflicts with the current state of the resource.",
        error_code: str = "CONFLICT",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=409,
            error_code=error_code,
            details=details,
        )


class UnprocessableEntityException(AppException):
    def __init__(
        self,
        message: str = "The request could not be processed.",
        error_code: str = "UNPROCESSABLE_ENTITY",
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=422,
            error_code=error_code,
            details=details,
        )