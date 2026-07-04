"""gameinput-mcp MCP server — thin stdio bridge to gameinput-daemon.

This process is spawned by VS Code via stdio. It has no game input logic.
All tool calls are forwarded over localhost HTTP to gameinput-daemon, which
you run in your own terminal. Ctrl+C the daemon — that's the kill switch.

    # One-time, in your terminal:
    uv run gameinput-daemon --config .gameinput/config.json

    # VS Code spawns this automatically via mcp.json (stdio).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

from common.log import MemLogger
from common.keymap_import import import_keymap_cli

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_DIR = pathlib.Path(
    os.getenv("GAMEINPUT_MCP_LOG_DIR",
              str(pathlib.Path(__file__).parent.parent.parent / "output"))
)
_mlog = MemLogger("gameinput_mcp", _LOG_DIR, level="info")
_logger = _mlog.get("server")

# ---------------------------------------------------------------------------
# Daemon HTTP helper
# ---------------------------------------------------------------------------

_daemon_url: str = os.getenv("GAMEINPUT_DAEMON_URL", "http://127.0.0.1:8767")


def _daemon(method: str, path: str, body: dict | None = None) -> Any:
    url = _daemon_url + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            raise RuntimeError(err.get("error", str(e)))
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(f"Daemon error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"gameinput-daemon not reachable at {_daemon_url}. "
            "Start it first: uv run gameinput-daemon --config your-config.json"
        )


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "gameinput-mcp",
    instructions=(
        "Sends keyboard/mouse input to user-declared game processes. "
        "You may ONLY call declared actions and macros — nothing else. "
        "Every action captures three screenshots (pre, +0.3s, +3s). "
        "The server is run by the user in their own terminal; "
        "Ctrl+C there cuts your access immediately."
    ),
)


@mcp.tool()
def list_targets() -> dict:
    """List all declared targets with their live status, allowed actions, and macros."""
    return _daemon("GET", "/targets")


@mcp.tool()
def list_actions(target: str) -> dict:
    """List all declared keymap actions for a target and their bindings."""
    return _daemon("GET", f"/actions?target={urllib.parse.quote(target)}")


@mcp.tool()
def list_macros(target: str) -> dict:
    """List all declared macros for a target with step previews."""
    return _daemon("GET", f"/macros?target={urllib.parse.quote(target)}")


@mcp.tool()
def press_action(target: str, action: str, modifier: str = "nrm") -> dict:
    """Press a single declared keymap action.

    ``modifier`` is ``"nrm"`` (normal) or ``"alt"``.
    Returns pre / +0.3s / +3s screenshots of the target window.
    """
    _logger.debug("press_action target=%s action=%s modifier=%s", target, action, modifier)
    return _daemon("POST", "/press_action",
                   {"target": target, "action": action, "modifier": modifier})


@mcp.tool()
def hold_action(target: str, action: str, duration_ms: int = 500, modifier: str = "nrm") -> dict:
    """Hold a declared keymap action for duration_ms milliseconds then release.

    Use this for movement — holding FORWARD for 1000ms walks forward for 1 second.
    Returns pre / +0.3s / +3s screenshots.
    """
    _logger.debug("hold_action target=%s action=%s duration=%dms", target, action, duration_ms)
    return _daemon("POST", "/hold_action",
                   {"target": target, "action": action,
                    "duration_ms": duration_ms, "modifier": modifier})


@mcp.tool()
def run_macro(target: str, macro: str) -> dict:
    """Execute a declared macro by name.

    Screenshots are captured relative to the START of the macro
    (pre / +0.3s / +3s).
    """
    _logger.debug("run_macro target=%s macro=%s", target, macro)
    return _daemon("POST", "/run_macro", {"target": target, "macro": macro})


@mcp.tool()
def screenshot(target: str) -> dict:
    """Capture the target window and return a single PNG screenshot."""
    return _daemon("GET", f"/screenshot?target={urllib.parse.quote(target)}")


@mcp.tool()
def get_window_info(target: str) -> dict:
    """Return window id, title, and geometry for the target process."""
    return _daemon("GET", f"/window?target={urllib.parse.quote(target)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "import-keymap":
        import_keymap_cli(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        prog="gameinput-mcp",
        description=(
            "gameinput-mcp: thin MCP stdio bridge to gameinput-daemon. "
            "VS Code spawns this automatically; you run gameinput-daemon "
            "separately in your terminal (Ctrl+C = kill switch)."
        ),
    )
    parser.add_argument(
        "--daemon-url",
        default=os.getenv("GAMEINPUT_DAEMON_URL", "http://127.0.0.1:8767"),
        help="Base URL of gameinput-daemon (default: http://127.0.0.1:8767)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("GAMEINPUT_MCP_LOG_LEVEL", "info"),
        help="Log level (trace/debug/info/warn/error)",
    )
    ns = parser.parse_args()

    global _mlog, _logger, _daemon_url
    _mlog = MemLogger("gameinput_mcp", _LOG_DIR, level=ns.log_level)
    _logger = _mlog.get("server")
    _daemon_url = ns.daemon_url

    _logger.info("gameinput-mcp started | daemon=%s", _daemon_url)

    try:
        mcp.run(transport="stdio")
    finally:
        _mlog.stop()
