"""Logging setup with TRACE level, ANSI-colored console, plain file output.

Inspired by lg-logger.lua. Console output is colored by level and prefixed
with the app name + module; file output is the same data minus the ANSI
codes. Both handlers run behind a QueueListener so log calls never block
the asyncio loop.

Levels (lowest to highest):
    TRACE   5   per-tick noise: "process found", "ping accepted", etc.
    DEBUG  10   diagnostic-only: raw protocol, dropped sends, etc.
    INFO   20   lifecycle events: startup, shutdown, launches, reconnects
    WARN   30   degraded but expected states: high RAM, ping timeout
    ERROR  40   ONLY when an exception was caught
    FATAL  50   process is about to abort

Configure via the ``log_level`` setting (case-insensitive: trace/debug/...).
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

# Matches stdlib's logging._ExcInfoType (which is private).
_ExcInfo = (
    bool
    | tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
    | BaseException
    | None
)

APP_NAME = "libmem_mcp"

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(logging.CRITICAL, "FATAL")


class TraceLogger(logging.Logger):
    """Logger subclass with a TRACE-level shortcut.

    Registered via :func:`logging.setLoggerClass` so every
    ``logging.getLogger(...)`` call after import returns one of these,
    and type checkers see ``trace`` as a real method instead of needing
    ``# type: ignore`` on every callsite.
    """

    def trace(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(TRACE):
            self.log(
                TRACE,
                msg,
                *args,
                exc_info=exc_info,
                stack_info=stack_info,
                stacklevel=stacklevel,
                extra=extra,
            )


logging.setLoggerClass(TraceLogger)


# ANSI colors per level (matches lg-logger.lua palette where reasonable)
_COLORS = {
    TRACE:            "\033[36m",  # cyan
    logging.DEBUG:    "\033[95m",  # bright magenta
    logging.INFO:     "\033[92m",  # bright green
    logging.WARNING:  "\033[93m",  # bright yellow
    logging.ERROR:    "\033[31m",  # red
    logging.CRITICAL: "\033[91m",  # bright red
}
_RESET = "\033[0m"
_DIM = "\033[2m"


class _ColorFormatter(logging.Formatter):
    """Console formatter: timestamps dim, app+module in brackets, level colored.

    Format: ``HH:MM:SS [libmem_mcp:module] [LEVEL] message``
    """

    def __init__(self, use_color: bool):
        super().__init__()
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        module = record.name if record.name != "root" else APP_NAME
        # Strip APP_NAME prefix from module names for brevity
        if module.startswith(APP_NAME + "."):
            module = module[len(APP_NAME) + 1:]
        level = record.levelname
        msg = record.getMessage()
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)

        if self.use_color:
            color = _COLORS.get(record.levelno, "")
            return (
                f"{_DIM}{ts}{_RESET} "
                f"[{APP_NAME}:{module}] "
                f"{color}[{level}]{_RESET} {msg}"
            )
        return f"{ts} [{APP_NAME}:{module}] [{level}] {msg}"


class _PlainFormatter(logging.Formatter):
    """File formatter: full timestamp, no colors."""

    def __init__(self):
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        module = record.name if record.name != "root" else APP_NAME
        if module.startswith(APP_NAME + "."):
            module = module[len(APP_NAME) + 1:]
        msg = record.getMessage()
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)
        return f"{ts} [{APP_NAME}:{module}] [{record.levelname}] {msg}"


def _resolve_level(name: str | int) -> int:
    if isinstance(name, int):
        return name
    n = name.strip().upper()
    if n == "TRACE":
        return TRACE
    if n == "FATAL":
        return logging.CRITICAL
    return logging.getLevelNamesMapping().get(n, logging.INFO)


def setup(
    log_file: Path,
    level: str | int = "info",
    use_color: bool = True,
) -> logging.handlers.QueueListener:
    """Wire the root logger.

    Console handler uses ANSI colors when stderr is a TTY. File handler
    writes plain text. Both run behind a QueueListener thread so callers
    never block on disk I/O.

    Returns the listener so the caller can `.stop()` it on shutdown.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_ColorFormatter(use_color))

    file = logging.FileHandler(log_file)
    file.setFormatter(_PlainFormatter())

    qhandler = logging.handlers.QueueHandler(log_queue)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(qhandler)
    root.setLevel(_resolve_level(level))

    listener = logging.handlers.QueueListener(log_queue, console, file)
    listener.start()
    return listener


def get_logger(name: str = APP_NAME) -> TraceLogger:
    """Return a :class:`TraceLogger` for the given name.

    Cast is sound because we registered ``TraceLogger`` via
    ``setLoggerClass`` at import time, so every getLogger call after this
    module is imported returns one.
    """
    logger = logging.getLogger(name)
    assert isinstance(logger, TraceLogger), (
        f"Expected TraceLogger, got {type(logger).__name__}. "
        f"Was libmem_mcp.log imported before any logger was created?"
    )
    return logger
