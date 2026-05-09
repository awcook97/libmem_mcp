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

Usage:
    mlog = MemLogger("my_app", Path("output"), level="trace")
    logger = mlog.get("server")   # logs as my_app.server
    logger.info("started")
    mlog.stop()                   # call on shutdown
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

    Format: ``HH:MM:SS [app_name:module] [LEVEL] message``
    """

    def __init__(self, app_name: str, use_color: bool) -> None:
        super().__init__()
        self.app_name = app_name
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        module = record.name if record.name != "root" else self.app_name
        if module.startswith(self.app_name + "."):
            module = module[len(self.app_name) + 1:]
        level = record.levelname
        msg = record.getMessage()
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)

        if self.use_color:
            color = _COLORS.get(record.levelno, "")
            return (
                f"{_DIM}{ts}{_RESET} "
                f"[{self.app_name}:{module}] "
                f"{color}[{level}]{_RESET} {msg}"
            )
        return f"{ts} [{self.app_name}:{module}] [{level}] {msg}"


class _PlainFormatter(logging.Formatter):
    """File formatter: full timestamp, no colors."""

    def __init__(self, app_name: str) -> None:
        super().__init__()
        self.app_name = app_name

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        module = record.name if record.name != "root" else self.app_name
        if module.startswith(self.app_name + "."):
            module = module[len(self.app_name) + 1:]
        msg = record.getMessage()
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)
        return f"{ts} [{self.app_name}:{module}] [{record.levelname}] {msg}"


def _resolve_level(name: str | int) -> int:
    if isinstance(name, int):
        return name
    n = name.strip().upper()
    if n == "TRACE":
        return TRACE
    if n == "FATAL":
        return logging.CRITICAL
    return logging.getLevelNamesMapping().get(n, logging.INFO)


class MemLogger:
    """Per-app logger: owns a named logger subtree, a log file, and a queue listener.

    Each instance attaches handlers to ``logging.getLogger(app_name)`` — not
    the root logger — with ``propagate = False``, so two MemLogger instances
    running in the same process never write into each other's log files.

    Usage::

        mlog = MemLogger("libmem_mcp", Path("output"), level="trace")
        log = mlog.get("server")
        log.info("started")
        # on shutdown:
        mlog.stop()
    """

    def __init__(
        self,
        app_name: str,
        log_dir: Path,
        level: str | int = "info",
        use_color: bool = True,
    ) -> None:
        self.app_name = app_name
        self.log_file = log_dir / f"{app_name}_autolog.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        resolved = _resolve_level(level)

        log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)

        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_ColorFormatter(app_name, use_color))

        fh = logging.FileHandler(self.log_file)
        fh.setFormatter(_PlainFormatter(app_name))

        qhandler = logging.handlers.QueueHandler(log_queue)

        app_logger = logging.getLogger(app_name)
        for h in list(app_logger.handlers):
            app_logger.removeHandler(h)
        app_logger.addHandler(qhandler)
        app_logger.setLevel(resolved)
        app_logger.propagate = False

        self._listener = logging.handlers.QueueListener(log_queue, console, fh)
        self._listener.start()

    def get(self, suffix: str = "") -> TraceLogger:
        """Return a TraceLogger for ``app_name`` or ``app_name.suffix``."""
        name = f"{self.app_name}.{suffix}" if suffix else self.app_name
        logger = logging.getLogger(name)
        assert isinstance(logger, TraceLogger), (
            f"Expected TraceLogger, got {type(logger).__name__}. "
            "Was common.log imported before any other logging call?"
        )
        return logger

    def stop(self) -> None:
        """Stop the background queue listener (call on shutdown)."""
        self._listener.stop()
