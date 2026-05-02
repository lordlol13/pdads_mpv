"""
Unified error handling and response structures for consistent API responses.

All endpoints should return standardized responses with proper status codes,
error details, and correlation IDs for tracking.
"""

from enum import Enum
from typing import Any, Optional, Generic, TypeVar
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Standardized error codes for client-side handling."""
    
    # Auth errors
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    
    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    
    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    RESOURCE_EXISTS = "RESOURCE_EXISTS"
    CONFLICT = "CONFLICT"
    
    # API errors
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    TIMEOUT = "TIMEOUT"
    
    # Server errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class ErrorDetail(BaseModel):
    """Detailed error information."""
    
    code: ErrorCode
    message: str
    field: Optional[str] = None  # For validation errors
    details: Optional[dict[str, Any]] = None


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""
    
    success: bool
    data: Optional[T] = None
    error: Optional[ErrorDetail] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": {},
                "error": None,
                "timestamp": "2026-04-10T12:00:00Z",
                "correlation_id": "req_abc123"
            }
        }
    )


def success_response(
    data: Any,
    correlation_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a successful API response."""
    return {
        "success": True,
        "data": data,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }


def error_response(
    code: ErrorCode,
    message: str,
    field: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create an error API response."""
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code.value,
            "message": message,
            "field": field,
            "details": details,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }


class AppException(Exception):
    """Base application exception with error code."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        field: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        self.details = details
        super().__init__(message)


class ValidationException(AppException):
    """Validation error."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            field=field,
            details=details,
        )


class AuthException(AppException):
    """Authentication error."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code=ErrorCode.AUTH_REQUIRED,
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class PermissionException(AppException):
    """Permission denied error."""
    
    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            code=ErrorCode.PERMISSION_DENIED,
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class NotFoundException(AppException):
    """Resource not found error."""
    
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=f"{resource} not found: {identifier}",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "identifier": str(identifier)},
        )


class ConflictException(AppException):
    """Resource conflict error."""
    
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class RateLimitException(AppException):
    """Rate limit exceeded."""
    
    def __init__(
        self,
        identifier: str,
        limit: int,
        window_seconds: int,
    ):
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message="Rate limit exceeded",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={
                "identifier": identifier,
                "limit": limit,
                "window_seconds": window_seconds,
            },
        )


class ExternalAPIException(AppException):
    """External API failure (News API, LLM, etc.)."""
    
    def __init__(
        self,
        service: str,
        message: str,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
    ):
        super().__init__(
            code=ErrorCode.EXTERNAL_API_ERROR,
            message=f"{service} error: {message}",
            status_code=status_code,
            details={"service": service},
        )


class DatabaseException(AppException):
    """Database operation error."""
    
    def __init__(self, message: str):
        super().__init__(
            code=ErrorCode.DATABASE_ERROR,
            message=f"Database error: {message}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ServiceUnavailableException(AppException):
    """Service temporarily unavailable."""
    
    def __init__(self, service: str = "Service"):
        super().__init__(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"{service} is temporarily unavailable. Please try again later.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"service": service},
        )


def to_http_exception(exc: AppException, correlation_id: Optional[str] = None) -> HTTPException:
    """Convert AppException to FastAPI HTTPException."""
    detail = error_response(
        code=exc.code,
        message=exc.message,
        field=exc.field,
        details=exc.details,
        correlation_id=correlation_id,
    )
    return HTTPException(status_code=exc.status_code, detail=detail)
