"""
Error handling — responses that never leak internals or PII.

THE RULE
    An error response tells the caller what to do about it, and nothing about
    how the system works. Stack traces, SQL fragments, table names, vendor
    responses and submitted field values all stay server-side.

WHY THAT MATTERS HERE MORE THAN USUALLY
    Validation errors are the leak nobody thinks about. FastAPI's default
    handler echoes the offending input back in the response — which for this
    platform means an Aadhaar number, a PAN, or a candidate's phone number
    landing in a client-side error toast, a browser console, and whatever
    front-end error tracker is installed. So we strip input values from
    validation output.

WHAT THE CALLER GETS INSTEAD
    A correlation ID. Support asks for it, an engineer greps the logs for it,
    and the full detail is there — on the server, where it belongs (SDD §6.6).
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from platform_core.auth.principal import NoPrincipalError
from platform_core.tenancy.context import TenantContextError

logger = logging.getLogger(__name__)


def _correlation_id(request: Request) -> str:
    """Read the correlation ID that CorrelationIdMiddleware put on the scope."""
    return str(request.scope.get("correlation_id", "unknown"))


def _error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    """
    Build a uniform error body.

    One shape for every error, so clients can handle failures generically:

        {"error": {"code": "...", "message": "...", "correlation_id": "..."}}

    Args:
        status_code: HTTP status to return.
        code: stable machine-readable identifier — clients branch on this, not
              on the message, which is free to change.
        message: human-readable, safe to display, contains no internals.
        correlation_id: ties this response to the server-side log entry.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": correlation_id,
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """
    Attach every exception handler to the application.

    Args:
        app: the FastAPI instance to register against.
    """

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Report which fields failed validation, without echoing their values.

        FastAPI's default includes an `input` key containing the submitted
        value. For this platform that is a PII leak in an error response, so we
        rebuild the error list keeping only the location and the reason.
        """
        correlation_id = _correlation_id(request)

        safe_errors: list[dict[str, Any]] = [
            {
                # e.g. ["body", "candidate", "aadhaar"] — names the field,
                # reveals nothing about what was submitted.
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "reason": error.get("msg", "invalid value"),
            }
            for error in exc.errors()
        ]

        # Log without the payload for the same reason.
        logger.warning(
            "Validation failed",
            extra={
                "correlation_id": correlation_id,
                "path": request.url.path,
                "field_count": len(safe_errors),
            },
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "One or more fields failed validation.",
                    "correlation_id": correlation_id,
                    "fields": safe_errors,
                }
            },
        )

    @app.exception_handler(TenantContextError)
    async def tenant_context_error_handler(
        request: Request, exc: TenantContextError
    ) -> JSONResponse:
        """
        No tenant established for a request that requires one.

        403 rather than 401: with real authentication the caller *is*
        authenticated, they simply have no organisation resolved. 401 would
        wrongly prompt a client to re-authenticate.
        """
        correlation_id = _correlation_id(request)
        logger.warning(
            "Request without tenant context",
            extra={"correlation_id": correlation_id, "path": request.url.path},
        )
        return _error_response(
            status.HTTP_403_FORBIDDEN,
            "no_organization_context",
            "No organisation is associated with this request.",
            correlation_id,
        )

    @app.exception_handler(NoPrincipalError)
    async def no_principal_handler(request: Request, exc: NoPrincipalError) -> JSONResponse:
        """
        No authenticated user for an endpoint that requires one.

        401 rather than 403: the caller is not authenticated at all, so
        re-authenticating is the correct next step. 403 is reserved for an
        authenticated user lacking a capability, where retrying the login
        would achieve nothing.

        The message is deliberately identical whether the user does not exist,
        belongs to another organisation, or is suspended. Distinguishing them
        would confirm the existence of accounts elsewhere.
        """
        correlation_id = _correlation_id(request)
        logger.warning(
            "Unauthenticated request to a protected endpoint",
            extra={"correlation_id": correlation_id, "path": request.url.path},
        )
        return _error_response(
            status.HTTP_401_UNAUTHORIZED,
            "not_authenticated",
            "Authentication is required for this action.",
            correlation_id,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """
        Database failure.

        The exception text can contain SQL, table names, column names and
        constraint definitions — a free schema disclosure. It is logged with the
        traceback and never returned.
        """
        correlation_id = _correlation_id(request)
        logger.exception("Database error", extra={"correlation_id": correlation_id})
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "database_error",
            "A database error occurred. Quote the correlation ID when reporting this.",
            correlation_id,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all.

        Anything reaching here is a bug. The caller gets a correlation ID; the
        traceback goes to the logs.
        """
        correlation_id = _correlation_id(request)
        logger.exception("Unhandled exception", extra={"correlation_id": correlation_id})
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred. Quote the correlation ID when reporting this.",
            correlation_id,
        )
