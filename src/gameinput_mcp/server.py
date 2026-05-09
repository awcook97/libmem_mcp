"""gameinput-mcp MCP server.

Run in YOUR terminal — Ctrl+C kills it and cuts off AI access entirely.

    uv run gameinput-mcp --config path/to/gameinput.config.json

The AI may ONLY call actions and macros that are declared in the config.
Nothing else can be sent to the target process.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import pathlib
import sys
import time
from typing import Any

import psutil
from mcp.server.fastmcp import FastMCP

from common.log import MemLogger
from common.config import Config, Target, load_config, resolve_config_path
from common.input_backend import GatedBackend, DisallowedKeyError
from common.keymap_import import import_keymap_cli
from gameinput_mcp.capture import capture_three, capture_single

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_DIR = pathlib.Path(
    os.getenv(
        "GAMEINPUT_MCP_LOG_DIR",
        str(pathlib.Path(__file__).parent.parent.parent / "output"),
    )
)
_mlog = MemLogger("gameinput_mcp", _LOG_DIR, level="trace")
_logger = _mlog.get("server")

# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _make_backend(target: Target) -> GatedBackend:
    platform = target.platform
    if platform == "auto":
        platform = "win32" if sys.platform == "win32" else "x11"

    if platform == "x11":
        from common.input_x11 import X11Backend
        raw = X11Backend()
    elif platform == "win32":
        from common.input_win32 import Win32Backend
        raw = Win32Backend()
    else:
        raise ValueError(f"Unknown platform: {platform!r}")

    return GatedBackend(raw, target.allowed_keys)


# ---------------------------------------------------------------------------
# Process / window resolution (per-call — PIDs can change)
# ---------------------------------------------------------------------------

def _find_pid(target: Target) -> int:
    """Find a live PID for this target."""
    if target.match_pid is not None:
        if psutil.pid_exists(target.match_pid):
            return target.match_pid
        raise RuntimeError(
            f"Target {target.name!r}: PID {target.match_pid} is not running"
        )
    if target.match_process_name:
        matches = [
            p for p in psutil.process_iter(["pid", "name"])
            if p.info["name"] == target.match_process_name
        ]
        if not matches:
            raise RuntimeError(
                f"Target {target.name!r}: no process named "
                f"{target.match_process_name!r} is running"
            )
        if len(matches) > 1:
            pids = [p.info["pid"] for p in matches]
            raise RuntimeError(
                f"Target {target.name!r}: multiple PIDs match "
                f"{target.match_process_name!r}: {pids}. "
                "Add 'pid' to the match block in your config to pin one."
            )
        return matches[0].info["pid"]
    raise RuntimeError(f"Target {target.name!r}: no match criteria defined")


# ---------------------------------------------------------------------------
# MCP server + global config state
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

_config: Config | None = None


def _get_config() -> Config:
    if _config is None:
        raise RuntimeError("Config not loaded — server was not started via main()")
    return _config


def _get_target(name: str) -> Target:
    cfg = _get_config()
    if name not in cfg.targets:
        raise ValueError(
            f"Unknown target {name!r}. Declared targets: "
            + ", ".join(cfg.targets)
        )
    return cfg.targets[name]


def _autolog(fn: Any) -> Any:
    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = fn.__name__
        arg_str = ", ".join(
            [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        )
        _logger.trace(">> %s(%s)", tool_name, arg_str)
        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
        except Exception as exc:
            _logger.error("!! %s raised %s: %s", tool_name, type(exc).__name__, exc)
            raise
        elapsed = (time.monotonic() - t0) * 1000
        try:
            summary = json.dumps(result, default=str)
            if len(summary) > 500:
                summary = summary[:500] + f"... [{len(summary)} chars]"
        except Exception:
            summary = repr(result)[:500]
        _logger.debug("<< %s  (%.1f ms)  %s", tool_name, elapsed, summary)
        return result
    return _wrapper


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@_autolog
def list_targets() -> dict:
    """List all declared targets with their live status, allowed actions, and macros."""
    cfg = _get_config()
    out = {}
    for t_name, target in cfg.targets.items():
        try:
            pid = _find_pid(target)
            alive = True
        except RuntimeError as e:
            pid = None
            alive = False
        keymap = cfg.keymaps.get(target.keymap_name, {})
        out[t_name] = {
            "alive": alive,
            "pid": pid,
            "match": {
                "name": target.match_process_name,
                "pid": target.match_pid,
            },
            "platform": target.platform,
            "keymap": target.keymap_name,
            "actions": sorted(keymap.keys()),
            "macros": sorted(target.macro_names),
        }
    return out


@mcp.tool()
@_autolog
def list_actions(target: str) -> dict:
    """List all declared keymap actions for a target and their bindings."""
    t = _get_target(target)
    cfg = _get_config()
    keymap = cfg.keymaps[t.keymap_name]
    return {
        action: {
            "nrm": entry.nrm,
            "alt": entry.alt,
            "nrm_bound": entry.nrm is not None,
            "alt_bound": entry.alt is not None,
        }
        for action, entry in keymap.items()
    }


@mcp.tool()
@_autolog
def list_macros(target: str) -> dict:
    """List all declared macros for a target with step previews."""
    t = _get_target(target)
    cfg = _get_config()
    return {
        name: [
            {"type": step.type, "value": step.value}
            for step in cfg.macros[name]
        ]
        for name in t.macro_names
    }


@mcp.tool()
@_autolog
async def press_action(
    target: str,
    action: str,
    modifier: str = "nrm",
) -> dict:
    """Press a single declared keymap action.

    ``modifier`` is ``"nrm"`` (normal) or ``"alt"``.
    Returns pre / +0.3s / +3s screenshots of the target window.
    """
    t = _get_target(target)
    cfg = _get_config()
    keymap = cfg.keymaps[t.keymap_name]

    if action not in keymap:
        raise ValueError(
            f"Action {action!r} is not in keymap {t.keymap_name!r}. "
            f"Declared actions: {sorted(keymap)}"
        )

    modifier = modifier.lower()
    if modifier not in ("nrm", "alt"):
        raise ValueError("modifier must be 'nrm' or 'alt'")

    entry = keymap[action]
    key = entry.nrm if modifier == "nrm" else entry.alt
    if key is None:
        raise ValueError(
            f"Action {action!r} modifier={modifier!r} is unbound (clear) "
            "in this keymap. No key will be pressed."
        )

    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)

    shoot = functools.partial(backend.screenshot, window)

    # Pre-shot, then send the key, then schedule post-shots.
    loop = asyncio.get_running_loop()
    pre_png = await loop.run_in_executor(None, shoot)
    from gameinput_mcp.capture import Capture, CaptureSet

    await loop.run_in_executor(None, backend.key_tap, window, key)

    async def _delayed(delay: float, label: str) -> Capture:
        await asyncio.sleep(delay)
        png = await loop.run_in_executor(None, shoot)
        return Capture(label, png)

    t0_3s, t3s = await asyncio.gather(
        _delayed(0.3, "t0_3s"),
        _delayed(3.0, "t3s"),
    )

    caps = CaptureSet(pre=Capture("pre", pre_png), t0_3s=t0_3s, t3s=t3s)
    return {
        "target": target,
        "action": action,
        "modifier": modifier,
        "key": key,
        "ok": True,
        "screenshots": caps.to_dict(),
    }


@mcp.tool()
@_autolog
async def run_macro(target: str, macro: str) -> dict:
    """Execute a declared macro by name.

    Screenshots are captured relative to the START of the macro
    (pre / +0.3s / +3s).
    """
    t = _get_target(target)
    cfg = _get_config()

    if macro not in t.macro_names:
        raise ValueError(
            f"Macro {macro!r} is not declared for target {target!r}. "
            f"Declared macros: {sorted(t.macro_names)}"
        )

    steps = cfg.macros[macro]
    keymap = cfg.keymaps[t.keymap_name]

    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)
    shoot = functools.partial(backend.screenshot, window)
    loop = asyncio.get_running_loop()

    pre_png = await loop.run_in_executor(None, shoot)

    # Execute macro steps synchronously (order matters).
    for idx, step in enumerate(steps):
        if step.type == "key":
            backend.key_tap(window, str(step.value))
        elif step.type == "text":
            backend.type_text(window, str(step.value))
        elif step.type == "delay":
            ms = step.value
            await asyncio.sleep(float(ms) / 1000.0 if isinstance(ms, (int, float, str)) else 0)
        elif step.type == "action":
            action_name = str(step.value)
            entry = keymap[action_name]
            if entry.nrm is None:
                raise DisallowedKeyError(
                    f"Macro {macro!r} step {idx}: action {action_name!r} "
                    "is unbound (clear)"
                )
            backend.key_tap(window, entry.nrm)
        elif step.type == "mouse":
            v = step.value
            if not isinstance(v, dict):
                raise ValueError(f"Macro {macro!r} step {idx}: mouse value must be a dict")
            backend.mouse_click(
                window,
                str(v.get("button", "left")),
                int(v.get("x", 0)),
                int(v.get("y", 0)),
                bool(v.get("relative", True)),
            )

    async def _delayed(delay: float, label: str):
        from gameinput_mcp.capture import Capture
        await asyncio.sleep(delay)
        png = await loop.run_in_executor(None, shoot)
        return Capture(label, png)

    from gameinput_mcp.capture import Capture, CaptureSet
    t0_3s, t3s = await asyncio.gather(
        _delayed(0.3, "t0_3s"),
        _delayed(3.0, "t3s"),
    )
    caps = CaptureSet(pre=Capture("pre", pre_png), t0_3s=t0_3s, t3s=t3s)

    return {
        "target": target,
        "macro": macro,
        "steps_executed": len(steps),
        "ok": True,
        "screenshots": caps.to_dict(),
    }


@mcp.tool()
@_autolog
async def screenshot(target: str) -> dict:
    """Capture the target window and return a single PNG screenshot."""
    t = _get_target(target)
    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)

    cap = await capture_single(functools.partial(backend.screenshot, window))
    return {
        "target": target,
        "screenshot": cap.to_dict(),
    }


@mcp.tool()
@_autolog
def get_window_info(target: str) -> dict:
    """Return window id, title, and geometry for the target process."""
    t = _get_target(target)
    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)
    info = backend.get_window_info(window)
    return {"target": target, **info}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gameinput-mcp",
        description=(
            "gameinput-mcp: send declared keyboard/mouse commands to game "
            "processes. Run in your own terminal — Ctrl+C cuts AI access."
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")

    # import-keymap subcommand
    sub.add_parser("import-keymap", add_help=False)

    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to gameinput.config.json (overrides env + workspace search)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("GAMEINPUT_MCP_LOG_LEVEL", "info"),
        help="Log level (trace/debug/info/warn/error)",
    )

    # Forward import-keymap to its own CLI (pass remaining args).
    if len(sys.argv) > 1 and sys.argv[1] == "import-keymap":
        import_keymap_cli(sys.argv[2:])
        return

    ns = parser.parse_args()

    # Re-construct MemLogger with the requested level.
    global _mlog, _logger
    _mlog = MemLogger("gameinput_mcp", _LOG_DIR, level=ns.log_level)
    _logger = _mlog.get("server")

    # Load config.
    global _config
    try:
        _config = load_config(ns.config)
    except (FileNotFoundError, ValueError) as exc:
        _logger.error("Config error: %s", exc)
        sys.exit(1)

    _logger.info(
        "gameinput-mcp started | targets: %s | config: %s",
        list(_config.targets),
        resolve_config_path(ns.config),
    )

    try:
        mcp.run()
    finally:
        _mlog.stop()
