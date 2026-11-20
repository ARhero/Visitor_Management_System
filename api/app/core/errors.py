from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class AppError(Exception):
    """Error rendered as ``{"error": {"code", "message", "details"}}``."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers
        super().__init__(message)


def not_found(what: str = "Resource") -> AppError:
    # Same response whether the row doesn't exist or belongs to another org.
    return AppError(404, "not_found", f"{what} not found")


def forbidden(message: str = "You do not have permission to do this") -> AppError:
    return AppError(403, "forbidden", message)


def conflict(message: str, details: Any = None) -> AppError:
    return AppError(409, "conflict", message, details)


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            _body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return JSONResponse(
            _body("validation_error", "Some fields are invalid", details), status_code=422
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Unique / FK violations not caught earlier by explicit checks.
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        return JSONResponse(
            _body("conflict", "This conflicts with existing data", {"constraint": constraint}),
            status_code=409,
        )
