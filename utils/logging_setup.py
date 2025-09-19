import json
import logging
import logging.config
import os
from datetime import datetime, timezone

LOG_RECORD_BUILTIN_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = self._prepare_log_dict(record)
        return json.dumps(message, default=str)

    def _prepare_log_dict(self, record: logging.LogRecord):
        always_fields = {
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
        }
        if record.exc_info:
            always_fields["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            always_fields["stack_info"] = self.formatStack(record.stack_info)

        # Base message
        message = {"level": record.levelname, "logger": record.name, **always_fields}

        # Add any extra fields from the log record
        for key, val in record.__dict__.items():
            if key not in LOG_RECORD_BUILTIN_ATTRS:
                message[key] = val
        return message


def setup_logging():
    """Sets up the logging configuration for the application."""
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    # Create the unique filename for the completion log here
    completion_log_filename = os.path.join(
        log_dir, f"completion_status_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {"format": "[%(levelname)s|%(name)s] %(message)s"},
            "summary_formatter": {
                "format": "%(asctime)s - %(levelname)s - %(message)s"
            },
            "json": {"()": __name__ + ".JsonFormatter"},
        },
        "handlers": {
            # Handlers for the main application logger
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "simple",
                "stream": "ext://sys.stdout",
            },
            "file_json": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "json",
                "filename": os.path.join(log_dir, "app.log.jsonl"),
                "maxBytes": 10485760,
                "backupCount": 5,
            },
            "error_file_json": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "json",
                "filename": os.path.join(log_dir, "error.log.jsonl"),
                "maxBytes": 10485760,
                "backupCount": 5,
            },
            # --- THIS IS THE NEW, DEDICATED HANDLER ---
            # Handler specifically for the completion status log file
            "completion_file_handler": {
                "class": "logging.FileHandler",
                "level": "INFO",
                "formatter": "summary_formatter",
                "filename": completion_log_filename,
            },
        },
        "loggers": {
            # --- THIS IS THE NEW LOGGER CONFIGURATION ---
            # Configure the dedicated summary logger
            "migration_summary": {
                "level": "INFO",
                # It sends messages to the console AND its own dedicated file
                "handlers": ["console", "completion_file_handler"],
                "propagate": False,  # Stop messages from going to the root logger
            }
        },
        "root": {
            "level": "INFO",
            # The root logger (used by 'SharePointMigration') logs to console and the JSON files
            "handlers": ["console", "file_json", "error_file_json"],
        },
    }
    logging.config.dictConfig(logging_config)


# A single logger instance for the main application logic
logger = logging.getLogger("SharePointMigration")
