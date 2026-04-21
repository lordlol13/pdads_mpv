"""
Structured logging configuration with JSON output, correlation IDs, and context.

Provides:
- JSON-structured logs for ELK/observability stacks
- Automatic correlation ID propagation
- Request/response logging middleware
- Performance logging
"""

import json
import logging
import logging.config
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone

import sys
import os

from app.backend.core.config import settings


class CorrelationIDFilter(logging.Filter):
    """Add correlation ID to all log records."""
    
    def __init__(self, default_correlation_id: str = "unknown"):
        super().__init__()
        self.default_correlation_id = default_correlation_id
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID if not already present."""
        if not hasattr(record, "correlation_id"):
            record.correlation_id = self.default_correlation_id
        return True


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to JSON."""
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add correlation ID if available
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id
        
        # Add extra fields from LoggerAdapter
        if hasattr(record, "extra"):
            log_obj.update(record.extra)
        
        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj, default=str)


def configure_logging():
    """Configure application logging with JSON output."""
    
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO
    
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Ensure stdout/stderr use UTF-8 where possible (helps Windows consoles)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        # Best-effort only; don't fail logging setup if reconfigure not available
        pass
    
    # On Windows rotating handlers can fail when another process holds the file.
    # Use non-rotating FileHandler locally on Windows to avoid PermissionError.
    file_handler_class = "logging.handlers.RotatingFileHandler"
    error_handler_class = "logging.handlers.RotatingFileHandler"
    file_handler_extra: dict = {"maxBytes": 10485760, "backupCount": 5}
    error_handler_extra: dict = {"maxBytes": 10485760, "backupCount": 5}
    if sys.platform.startswith("win"):
        file_handler_class = "logging.FileHandler"
        error_handler_class = "logging.FileHandler"
        file_handler_extra = {}
        error_handler_extra = {}

    # Logging configuration
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": CorrelationIDFilter,
                "default_correlation_id": "app-startup",
            }
        },
        "formatters": {
            "json": {
                "()": JSONFormatter,
            },
            "verbose": {
                "format": "[%(asctime)s] %(levelname)s %(name)s:%(lineno)d - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "json" if not settings.DEBUG else "verbose",
                "stream": "ext://sys.stdout",
                "filters": ["correlation_id"],
            },
            "file": {
                "class": file_handler_class,
                "level": log_level,
                "formatter": "json",
                "filename": str(log_dir / "app.log"),
                "encoding": "utf-8",
                **file_handler_extra,
                "filters": ["correlation_id"],
            },
            "error_file": {
                "class": error_handler_class,
                "level": logging.ERROR,
                "formatter": "json",
                "filename": str(log_dir / "app_error.log"),
                "encoding": "utf-8",
                **error_handler_extra,
                "filters": ["correlation_id"],
            },
        },
        "loggers": {
            # Application loggers
            "app": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False,
            },
            # Framework loggers
            "fastapi": {
                "level": logging.WARNING,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn": {
                "level": logging.WARNING,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            # Database
            "sqlalchemy": {
                "level": logging.WARNING,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            # Cache/Queue
            "redis": {
                "level": logging.WARNING,
                "handlers": ["console"],
                "propagate": False,
            },
            "celery": {
                "level": logging.INFO,
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
        },
    }
    
    logging.config.dictConfig(config)


class ContextLogger:
    """Logger with built-in context (correlation ID, user ID, etc.)."""
    
    def __init__(self, name: str, correlation_id: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.correlation_id = correlation_id or "unknown"
        self.context: Dict[str, Any] = {}
    
    def set_correlation_id(self, correlation_id: str):
        """Set correlation ID for all subsequent logs."""
        self.correlation_id = correlation_id
    
    def set_context(self, **kwargs):
        """Set additional context (user_id, request_path, etc.)."""
        self.context.update(kwargs)
    
    def _log(
        self,
        level: int,
        message: str,
        **extra,
    ):
        """Internal logging method with context."""
        extra_data = {
            "correlation_id": self.correlation_id,
            **self.context,
            **extra,
        }
        
        self.logger.log(
            level,
            message,
            extra=extra_data,
        )
    
    def debug(self, message: str, **extra):
        self._log(logging.DEBUG, message, **extra)
    
    def info(self, message: str, **extra):
        self._log(logging.INFO, message, **extra)
    
    def warning(self, message: str, **extra):
        self._log(logging.WARNING, message, **extra)
    
    def error(self, message: str, **extra):
        self._log(logging.ERROR, message, **extra)
    
    def critical(self, message: str, **extra):
        self._log(logging.CRITICAL, message, **extra)
    
    def exception(self, message: str, exc_info=True, **extra):
        """Log exception with full traceback."""
        self.logger.exception(message, exc_info=exc_info, extra=extra)


# Initialize logging on import
configure_logging()

# Get application logger
logger = logging.getLogger("app")
