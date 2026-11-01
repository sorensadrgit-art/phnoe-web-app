"""Bounded local failure diagnostics without exception or user-source text."""
from __future__ import annotations

import logging
import sys

_LOCATIONS = {
    "oversize_body_drain_failed": ("t6_server", "_body"),
    "unexpected_local_api_error": ("t6_server", "do_POST"),
    "unexpected_local_get_error": ("t6_server", "do_GET"),
    "local_get_storage_error": ("t6_server", "do_GET"),
    "local_post_storage_error": ("t6_server", "do_POST"),
    "local_request_handler_failed": ("t6_server", "handle_error"),
    "library_register_storage_error": ("session_library", "register_session"),
    "library_stage_storage_error": ("session_library", "stage_take"),
    "library_accept_storage_error": ("session_library", "accept_take"),
    "capture_status_storage_error": ("t6_service", "_poll_webcam"),
    "capture_probe_failed": ("capture_station", "probe_clip"),
    "local_server_failed": ("t6_server", "main"),
    "local_service_cleanup_failed": ("t6_service", "__del__"),
    "local_backup_inspection_failed": ("t6_service", "backups"),
}
_TYPE_LABELS: dict[type[BaseException], str] = {
    OSError: "OSError",
    FileNotFoundError: "FileNotFoundError",
    PermissionError: "PermissionError",
    TimeoutError: "TimeoutError",
    RuntimeError: "RuntimeError",
    ValueError: "ValueError",
    TypeError: "TypeError",
    OverflowError: "OverflowError",
}
_LEVEL_LABELS = {logging.WARNING: "WARNING", logging.ERROR: "ERROR"}


def _exception_label(error: BaseException) -> str:
    error_type = type(error)
    label = _TYPE_LABELS.get(error_type)
    if label is not None:
        return label
    # Closed house label, without importing the backup implementation or
    # serializing arbitrary class names. This is classification, not attestation.
    if (error_type.__module__ == "backup_manager"
            and error_type.__qualname__ == "BackupCorruptError"):
        return "BackupCorruptError"
    return "OtherException"


def log_local_failure(logger: logging.Logger, level: int, event: str,
                      error: BaseException) -> None:
    """Emit only fixed labels, a known basename/line, and standard numeric time."""
    module, function = _LOCATIONS[event]
    level_label = _LEVEL_LABELS[level]
    if not logger.isEnabledFor(level):
        return
    line = sys._getframe(1).f_lineno
    basename = module + ".py"
    message = (f"event={event} exception_type={_exception_label(error)} "
               f"location={basename}:{line}")
    # Bypass LogRecordFactory and logger.findCaller: neither arbitrary factory
    # extras nor absolute source paths/stack text belong in these records.
    record = logging.LogRecord(module, level, basename, line, message, (), None, function)
    record.levelname = level_label
    record.threadName = "local"
    record.processName = "local"
    record.taskName = None
    record.exc_text = None
    record.stack_info = None
    logger.handle(record)
