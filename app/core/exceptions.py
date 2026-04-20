import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)


class ChatToSalesError(Exception):
    """Base application exception."""

    def __init__(
        self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    ):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(ChatToSalesError):
    def __init__(self, resource: str, identifier: str | int):
        super().__init__(
            message=f"{resource} '{identifier}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictError(ChatToSalesError):
    def __init__(self, message: str):
        super().__init__(message=message, status_code=status.HTTP_409_CONFLICT)


class UnauthorizedError(ChatToSalesError):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(ChatToSalesError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN)


class InvalidWebhookSignatureError(ChatToSalesError):
    def __init__(self):
        super().__init__(
            message="Webhook signature verification failed.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


# ── Exception handlers (register these in main.py) ───────────────────────────


async def chattosales_error_handler(
    request: Request, exc: ChatToSalesError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "An unexpected error occurred."},
    )
