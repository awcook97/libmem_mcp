"""gameinput-daemon — HTTP input bridge.

Run this in YOUR terminal. Ctrl+C = kill switch. The AI gets nothing.

    uv run gameinput-daemon --config .gameinput/config.json

The gameinput-mcp MCP server (stdio, spawned by VS Code) calls this over
localhost HTTP. All key/mouse/screenshot operations happen here.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import psutil

from common.log import MemLogger
from common.config import Config, Target, load_config, resolve_config_path
from common.input_backend import GatedBackend, DisallowedKeyError
from common.keymap_import import import_keymap_cli
from gameinput_mcp.capture import Capture, CaptureSet

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_DIR = pathlib.Path(
    os.getenv("GAMEINPUT_MCP_LOG_DIR",
              str(pathlib.Path(__file__).parent.parent.parent / "output"))
)
_mlog = MemLogger("gameinput_daemon", _LOG_DIR, level="debug")
_logger = _mlog.get("daemon")

# ---------------------------------------------------------------------------
# Kill bit
# ---------------------------------------------------------------------------

KILL_BIT: pathlib.Path = pathlib.Path(
    os.getenv("GAMEINPUT_KILL_BIT", "/tmp/SHUTDOWN_AI")  # noqa: S108
)


def _check_kill_bit() -> None:
    """Raise RuntimeError if the kill bit is set. Called before every input action."""
    if KILL_BIT.exists():
        raise RuntimeError(
            f"Kill bit is set ({KILL_BIT}). "
            "All AI input blocked. Remove the file or POST /killswitch {{\"active\": false}} to resume."
        )


def _impl_killswitch(active: bool) -> dict:
    if active:
        KILL_BIT.touch()
        _logger.warning("Kill bit SET — all input actions blocked")
    else:
        KILL_BIT.unlink(missing_ok=True)
        _logger.warning("Kill bit CLEARED — input actions unblocked")
    return {"active": KILL_BIT.exists(), "path": str(KILL_BIT)}


# ---------------------------------------------------------------------------
# ffmpeg window capture (works even when window is occluded)
# ---------------------------------------------------------------------------

def _ffmpeg_screenshot(window_id: int, display: str = ":0") -> bytes:
    """Grab a single frame from the window via ffmpeg x11grab.

    Uses the compositor-composited buffer, so it captures correctly even when
    the window is behind other windows. Returns PNG bytes.
    """
    wid_hex = hex(window_id)
    result = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error",
            "-f", "x11grab",
            "-window_id", wid_hex,
            "-i", display,
            "-vframes", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "pipe:1",
        ],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout:
        err = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffmpeg capture failed (wid={wid_hex}): {err}")
    return result.stdout


# ---------------------------------------------------------------------------
# Backend / process helpers
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


def _find_pid(target: Target) -> int:
    if target.match_pid is not None:
        if psutil.pid_exists(target.match_pid):
            return target.match_pid
        raise RuntimeError(f"Target {target.name!r}: PID {target.match_pid} not running")
    if target.match_process_name:
        matches = [p for p in psutil.process_iter(["pid", "name"])
                   if p.info["name"] == target.match_process_name]
        if not matches:
            raise RuntimeError(
                f"Target {target.name!r}: no process named {target.match_process_name!r}")
        if len(matches) > 1:
            pids = [p.info["pid"] for p in matches]
            raise RuntimeError(
                f"Target {target.name!r}: multiple PIDs {pids} — "
                "add 'pid' to the match block in your config")
        return matches[0].info["pid"]
    raise RuntimeError(f"Target {target.name!r}: no match criteria defined")


def _get_target(cfg: Config, name: str) -> Target:
    if name not in cfg.targets:
        raise ValueError(f"Unknown target {name!r}. Declared: {list(cfg.targets)}")
    return cfg.targets[name]


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _impl_list_targets(cfg: Config) -> dict:
    out = {}
    for t_name, target in cfg.targets.items():
        try:
            pid = _find_pid(target)
            alive = True
        except RuntimeError:
            pid = None
            alive = False
        keymap = cfg.keymaps.get(target.keymap_name, {})
        out[t_name] = {
            "alive": alive,
            "pid": pid,
            "match": {"name": target.match_process_name, "pid": target.match_pid},
            "platform": target.platform,
            "keymap": target.keymap_name,
            "actions": sorted(keymap.keys()),
            "macros": sorted(target.macro_names),
        }
    return out


def _impl_list_actions(cfg: Config, target_name: str) -> dict:
    t = _get_target(cfg, target_name)
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


def _impl_list_macros(cfg: Config, target_name: str) -> dict:
    t = _get_target(cfg, target_name)
    return {
        name: [{"type": step.type, "value": step.value} for step in cfg.macros[name]]
        for name in t.macro_names
    }


def _impl_screenshot(cfg: Config, target_name: str) -> dict:
    t = _get_target(cfg, target_name)
    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)
    png = _ffmpeg_screenshot(window)
    return {"target": target_name, "screenshot": Capture("screenshot", png).to_dict()}


def _impl_window(cfg: Config, target_name: str) -> dict:
    t = _get_target(cfg, target_name)
    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)
    return {"target": target_name, **backend.get_window_info(window)}


def _three_shots(window: int, pre_png: bytes) -> CaptureSet:
    """Take +0.3s and +3s screenshots via ffmpeg in parallel threads.

    Captures through the compositor — works even if the window is occluded.
    """
    shots: dict[str, bytes] = {}

    def _shoot(delay: float, label: str) -> None:
        time.sleep(delay)
        try:
            shots[label] = _ffmpeg_screenshot(window)
        except RuntimeError as e:
            _logger.warning("Post-shot %s failed: %s", label, e)

    th1 = threading.Thread(target=_shoot, args=(0.3, "t0_3s"), daemon=True)
    th2 = threading.Thread(target=_shoot, args=(3.0, "t3s"), daemon=True)
    th1.start(); th2.start()
    th1.join(timeout=4.0); th2.join(timeout=4.0)

    return CaptureSet(
        pre=Capture("pre", pre_png),
        t0_3s=Capture("t0_3s", shots.get("t0_3s", pre_png)),
        t3s=Capture("t3s", shots.get("t3s", pre_png)),
    )


def _impl_press_action(
    cfg: Config, target_name: str, action: str, modifier: str
) -> dict:
    t = _get_target(cfg, target_name)
    keymap = cfg.keymaps[t.keymap_name]
    if action not in keymap:
        raise ValueError(f"Action {action!r} not in keymap {t.keymap_name!r}. "
                         f"Declared: {sorted(keymap)}")
    modifier = modifier.lower()
    if modifier not in ("nrm", "alt"):
        raise ValueError("modifier must be 'nrm' or 'alt'")
    entry = keymap[action]
    key = entry.nrm if modifier == "nrm" else entry.alt
    if key is None:
        raise ValueError(f"Action {action!r} modifier={modifier!r} is unbound (clear)")

    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)

    _check_kill_bit()
    _logger.debug("press_action target=%s action=%s key=%s", target_name, action, key)
    pre_png = _ffmpeg_screenshot(window)
    backend.key_tap(window, key)
    caps = _three_shots(window, pre_png)

    return {
        "target": target_name,
        "action": action,
        "modifier": modifier,
        "key": key,
        "ok": True,
        "screenshots": caps.to_dict(),
    }


def _impl_hold_action(
    cfg: Config, target_name: str, action: str, duration_ms: int, modifier: str
) -> dict:
    """Hold a key for duration_ms milliseconds then release."""
    t = _get_target(cfg, target_name)
    keymap = cfg.keymaps[t.keymap_name]
    if action not in keymap:
        raise ValueError(f"Action {action!r} not in keymap {t.keymap_name!r}. "
                         f"Declared: {sorted(keymap)}")
    modifier = modifier.lower()
    entry = keymap[action]
    key = entry.nrm if modifier == "nrm" else entry.alt
    if key is None:
        raise ValueError(f"Action {action!r} modifier={modifier!r} is unbound (clear)")

    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)

    _check_kill_bit()
    _logger.debug("hold_action target=%s action=%s key=%s duration=%dms",
                  target_name, action, key, duration_ms)
    pre_png = _ffmpeg_screenshot(window)
    backend.key_press(window, key)
    time.sleep(duration_ms / 1000.0)
    backend.key_release(window, key)
    caps = _three_shots(window, pre_png)

    return {
        "target": target_name,
        "action": action,
        "modifier": modifier,
        "key": key,
        "duration_ms": duration_ms,
        "ok": True,
        "screenshots": caps.to_dict(),
    }


def _impl_run_macro(cfg: Config, target_name: str, macro: str) -> dict:
    t = _get_target(cfg, target_name)
    if macro not in t.macro_names:
        raise ValueError(f"Macro {macro!r} not declared for {target_name!r}. "
                         f"Declared: {sorted(t.macro_names)}")
    steps = cfg.macros[macro]
    keymap = cfg.keymaps[t.keymap_name]
    pid = _find_pid(t)
    backend = _make_backend(t)
    window = backend.find_window(pid, t.window_title_regex)

    _check_kill_bit()
    _logger.debug("run_macro target=%s macro=%s steps=%d", target_name, macro, len(steps))
    pre_png = _ffmpeg_screenshot(window)

    for idx, step in enumerate(steps):
        if step.type == "key":
            backend.key_tap(window, str(step.value))
        elif step.type == "text":
            backend.type_text(window, str(step.value))
        elif step.type == "delay":
            time.sleep(float(step.value) / 1000.0)  # type: ignore[arg-type]
        elif step.type == "hold":
            # {"type": "hold", "value": {"action": "FORWARD", "ms": 2000}}
            v = step.value
            if not isinstance(v, dict):
                raise ValueError(f"Macro {macro!r} step {idx}: hold value must be a dict")
            hold_action = str(v["action"])
            hold_ms = float(v.get("ms", 500))
            hold_key = keymap[hold_action].nrm
            if hold_key is None:
                raise DisallowedKeyError(
                    f"Macro {macro!r} step {idx}: hold action {hold_action!r} is unbound")
            backend.key_press(window, hold_key)
            time.sleep(hold_ms / 1000.0)
            backend.key_release(window, hold_key)
        elif step.type == "action":
            entry = keymap[str(step.value)]
            if entry.nrm is None:
                raise DisallowedKeyError(
                    f"Macro {macro!r} step {idx}: action {step.value!r} is unbound")
            backend.key_tap(window, entry.nrm)
        elif step.type == "mouse":
            v = step.value
            if not isinstance(v, dict):
                raise ValueError(
                    f"Macro {macro!r} step {idx}: mouse value must be a dict")
            backend.mouse_click(
                window,
                str(v.get("button", "left")),
                int(v.get("x", 0)),
                int(v.get("y", 0)),
                bool(v.get("relative", True)),
            )

    caps = _three_shots(window, pre_png)
    return {
        "target": target_name,
        "macro": macro,
        "steps_executed": len(steps),
        "ok": True,
        "screenshots": caps.to_dict(),
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    cfg: Config  # set as class var before serving

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _route(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        route = parsed.path
        body = self._read_body() if method == "POST" else {}

        routes: dict[tuple[str, str], Any] = {
            ("GET",  "/targets"):      lambda: _impl_list_targets(self.cfg),
            ("GET",  "/actions"):      lambda: _impl_list_actions(self.cfg, params["target"]),
            ("GET",  "/macros"):       lambda: _impl_list_macros(self.cfg, params["target"]),
            ("GET",  "/screenshot"):   lambda: _impl_screenshot(self.cfg, params["target"]),
            ("GET",  "/window"):       lambda: _impl_window(self.cfg, params["target"]),
            ("GET",  "/killswitch"):   lambda: {"active": KILL_BIT.exists(), "path": str(KILL_BIT)},
            ("POST", "/press_action"): lambda: _impl_press_action(
                self.cfg, body["target"], body["action"], body.get("modifier", "nrm")),
            ("POST", "/hold_action"):  lambda: _impl_hold_action(
                self.cfg, body["target"], body["action"],
                int(body.get("duration_ms", 500)), body.get("modifier", "nrm")),
            ("POST", "/run_macro"):    lambda: _impl_run_macro(
                self.cfg, body["target"], body["macro"]),
            ("POST", "/killswitch"):   lambda: _impl_killswitch(bool(body.get("active", True))),
        }

        fn = routes.get((method, route))
        if fn is None:
            self._send_json({"error": f"No route {method} {route}"}, 404)
            return

        try:
            self._send_json(fn())
        except (KeyError, ValueError, DisallowedKeyError) as e:
            _logger.warning("%s %s -> 400: %s", method, route, e)
            self._send_json({"error": str(e)}, 400)
        except RuntimeError as e:
            _logger.warning("%s %s -> 503: %s", method, route, e)
            self._send_json({"error": str(e)}, 503)
        except Exception as e:
            _logger.exception("Unhandled error on %s %s", method, route)
            self._send_json({"error": str(e)}, 500)

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _logger.debug(format, *args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "import-keymap":
        import_keymap_cli(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        prog="gameinput-daemon",
        description=(
            "gameinput-daemon: HTTP bridge for game input. "
            "Run in your terminal — Ctrl+C kills it and cuts off all AI access."
        ),
    )
    parser.add_argument("--config", metavar="PATH", default=None,
                        help="Path to gameinput.config.json")
    parser.add_argument("--port", type=int,
                        default=int(os.getenv("GAMEINPUT_DAEMON_PORT", "8767")),
                        help="Port to listen on (default: 8767)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--log-level",
                        default=os.getenv("GAMEINPUT_DAEMON_LOG_LEVEL", "debug"),
                        help="Log level (trace/debug/info/warn/error)")
    ns = parser.parse_args()

    global _mlog, _logger
    _mlog = MemLogger("gameinput_daemon", _LOG_DIR, level=ns.log_level)
    _logger = _mlog.get("daemon")

    try:
        cfg = load_config(ns.config)
    except (FileNotFoundError, ValueError) as e:
        _logger.error("Config error: %s", e)
        sys.exit(1)

    _Handler.cfg = cfg

    server = ThreadingHTTPServer((ns.host, ns.port), _Handler)
    _logger.info(
        "gameinput-daemon listening on http://%s:%d | targets: %s | config: %s",
        ns.host, ns.port, list(cfg.targets), resolve_config_path(ns.config),
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _logger.info("gameinput-daemon stopped")
        _mlog.stop()
