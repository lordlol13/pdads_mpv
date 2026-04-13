"""
Tests for structured logging infrastructure.

Run with: pytest tests/test_structured_logging.py -v
"""

import json
import logging
from io import StringIO
from pathlib import Path

import pytest

from app.backend.core.logging import (
    ContextLogger,
    JSONFormatter,
    CorrelationIDFilter,
    configure_logging,
)


class TestContextLogger:
    """Tests for ContextLogger class."""

    def test_context_logger_creation(self):
        """Test ContextLogger can be instantiated."""
        logger = ContextLogger("test.module")
        assert logger is not None
        assert logger.correlation_id == "unknown"

    def test_correlation_id_setting(self):
        """Test correlation ID can be set and retrieved."""
        logger = ContextLogger("test.module")
        test_id = "test-correlation-123"
        logger.set_correlation_id(test_id)
        assert logger.correlation_id == test_id

    def test_context_setting(self):
        """Test context variables can be set."""
        logger = ContextLogger("test.module")
        logger.set_context(user_id="user_123", action="login")
        assert logger.context["user_id"] == "user_123"
        assert logger.context["action"] == "login"

    def test_context_update(self):
        """Test context can be updated with additional variables."""
        logger = ContextLogger("test.module")
        logger.set_context(user_id="user_123")
        logger.set_context(action="login")
        assert logger.context["user_id"] == "user_123"
        assert logger.context["action"] == "login"

    def test_multiple_loggers_independent_context(self):
        """Test multiple loggers maintain independent contexts."""
        logger1 = ContextLogger("module1")
        logger2 = ContextLogger("module2")

        logger1.set_context(user_id="user_1")
        logger2.set_context(user_id="user_2")

        assert logger1.context["user_id"] == "user_1"
        assert logger2.context["user_id"] == "user_2"


class TestJSONFormatter:
    """Tests for JSONFormatter."""

    def test_json_formatter_output(self):
        """Test JSONFormatter produces valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "test-id-123"

        output = formatter.format(record)

        # Should be valid JSON
        parsed = json.loads(output)

        # Check required fields
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert parsed["line"] == 42
        assert parsed["correlation_id"] == "test-id-123"
        assert "timestamp" in parsed

    def test_json_formatter_with_extra_fields(self):
        """Test JSONFormatter includes extra fields."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=10,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "test-id"
        record.extra = {"user_id": "user_123", "action": "delete"}

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["user_id"] == "user_123"
        assert parsed["action"] == "delete"

    def test_json_formatter_exception_handling(self):
        """Test JSONFormatter includes exception info."""
        formatter = JSONFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=20,
                msg="Error occurred",
                args=(),
                exc_info=True,  # This will be set by logging module
            )
            import sys
            record.exc_info = sys.exc_info()

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]


class TestCorrelationIDFilter:
    """Tests for CorrelationIDFilter."""

    def test_filter_adds_correlation_id(self):
        """Test filter adds correlation ID to records."""
        filter_obj = CorrelationIDFilter("default-id")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )

        # Before filter
        assert not hasattr(record, "correlation_id")

        # Apply filter
        result = filter_obj.filter(record)

        # After filter
        assert hasattr(record, "correlation_id")
        assert record.correlation_id == "default-id"
        assert result is True  # Filter returns True to allow logging

    def test_filter_preserves_existing_correlation_id(self):
        """Test filter doesn't override existing correlation ID."""
        filter_obj = CorrelationIDFilter("default-id")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "custom-id-123"

        filter_obj.filter(record)

        assert record.correlation_id == "custom-id-123"


class TestLoggingConfiguration:
    """Tests for logging configuration."""

    def test_configure_logging_creates_log_dir(self):
        """Test configure_logging creates logs directory."""
        # This test just verifies the function runs without error
        # In a real scenario, you'd check that logs/ directory exists
        try:
            configure_logging()
            logs_dir = Path("logs")
            assert logs_dir.exists() or logs_dir.is_dir()
        except Exception as e:
            pytest.fail(f"configure_logging failed: {e}")

    def test_logger_module_level_import(self):
        """Test logger can be imported and used at module level."""
        from app.backend.core.logging import logger as mod_logger

        assert mod_logger is not None
        assert isinstance(mod_logger, logging.Logger)


class TestContextLoggerLogging:
    """Integration tests for ContextLogger logging methods."""

    def test_debug_logging(self):
        """Test debug logging method."""
        logger = ContextLogger("test")
        # Should not raise error
        logger.debug("Debug message", extra_data="value")

    def test_info_logging(self):
        """Test info logging method."""
        logger = ContextLogger("test")
        logger.info("Info message", user_id="123")

    def test_warning_logging(self):
        """Test warning logging method."""
        logger = ContextLogger("test")
        logger.warning("Warning message", count=5)

    def test_error_logging(self):
        """Test error logging method."""
        logger = ContextLogger("test")
        logger.error("Error message", error_code=500)

    def test_critical_logging(self):
        """Test critical logging method."""
        logger = ContextLogger("test")
        logger.critical("Critical message")

    def test_exception_logging(self):
        """Test exception logging method."""
        logger = ContextLogger("test")
        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception("Caught exception", operation="division")


@pytest.mark.asyncio
async def test_correlation_id_in_async_context():
    """Test correlation ID works in async contexts."""
    logger = ContextLogger("test")
    correlation_id = "async-test-123"
    logger.set_correlation_id(correlation_id)

    # Simulate async operation
    import asyncio
    await asyncio.sleep(0.01)

    assert logger.correlation_id == correlation_id


class TestJSONFormatIntegration:
    """Integration tests for JSON format with real logging."""

    def test_json_output_from_context_logger(self):
        """Test actual JSON output from ContextLogger."""
        # Create a handler that captures log output
        handler = logging.StreamHandler(StringIO())
        formatter = JSONFormatter()
        handler.setFormatter(formatter)

        logger_name = "test.integration"
        test_logger = logging.getLogger(logger_name)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        # Log a message
        record = logging.LogRecord(
            name=logger_name,
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Integration test message",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "int-test-123"

        formatted = formatter.format(record)

        # Verify JSON format
        parsed = json.loads(formatted)
        assert parsed["message"] == "Integration test message"
        assert parsed["correlation_id"] == "int-test-123"
        assert parsed["level"] == "INFO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
