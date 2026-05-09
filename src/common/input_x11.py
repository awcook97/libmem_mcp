"""X11 input + screenshot backend using xdotool and mss.

Requires xdotool to be installed as a system package::

    sudo apt install xdotool   # Debian/Ubuntu
    sudo pacman -S xdotool     # Arch

Screenshots use python-mss (pure Python, no ImageMagick dep) filtered to the
window's bounding rect, discovered via Xlib.  If python-xlib is not installed
the screenshot falls back to a full-display capture (mss screen 0) cropped by
xdotool getwindowgeometry output.
"""
from __future__ import annotations

import io
import re
import subprocess
import time
from typing import Any

try:
    from Xlib import display as _xdisplay  # type: ignore[import]
    _XLIB: bool = True
except ImportError:
    _xdisplay = None  # type: ignore[assignment]
    _XLIB = False

try:
    import mss as _mss  # type: ignore[import]
    import mss.tools as _mss_tools  # type: ignore[import]
    _MSS: bool = True
except ImportError:
    _mss = None  # type: ignore[assignment]
    _mss_tools = None  # type: ignore[assignment]
    _MSS = False


def _xdotool(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["xdotool", *args],
        capture_output=True,
        text=True,
        check=check,
    )


class X11Backend:
    """X11 backend: all input scoped to a specific window via xdotool --window."""

    # Small delay between key-down and key-up for a tap.
    _TAP_DELAY = 0.05

    def find_window(self, pid: int, title_regex: str | None = None) -> int:
        """Return an xdotool window id for the process."""
        if title_regex:
            result = _xdotool(
                "search", "--pid", str(pid), "--name", title_regex, check=False
            )
        else:
            result = _xdotool("search", "--pid", str(pid), check=False)

        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"No X11 window found for PID {pid}"
                + (f" matching {title_regex!r}" if title_regex else "")
            )

        ids = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        if len(ids) > 1 and title_regex is None:
            raise RuntimeError(
                f"PID {pid} owns {len(ids)} windows; "
                "set 'window_title_regex' in your config to select one"
            )
        return int(ids[0])

    def key_press(self, window: int, key: str) -> None:
        _xdotool("keydown", "--window", str(window), key)

    def key_release(self, window: int, key: str) -> None:
        _xdotool("keyup", "--window", str(window), key)

    def key_tap(self, window: int, key: str) -> None:
        _xdotool("keydown", "--window", str(window), key)
        time.sleep(self._TAP_DELAY)
        _xdotool("keyup", "--window", str(window), key)

    def type_text(self, window: int, text: str) -> None:
        # xdotool type handles the encoding; we scope to the window.
        _xdotool("type", "--window", str(window), "--clearmodifiers", "--", text)

    def mouse_click(
        self, window: int, button: str, x: int, y: int, relative: bool = True
    ) -> None:
        btn_map = {"left": "1", "middle": "2", "right": "3"}
        btn = btn_map.get(button.lower(), button)
        if relative:
            _xdotool(
                "mousemove", "--window", str(window), str(x), str(y),
                "click", btn,
            )
        else:
            _xdotool("mousemove", str(x), str(y), "click", btn)

    def screenshot(self, window: int) -> bytes:
        if _MSS:
            return self._screenshot_mss(window)
        return self._screenshot_xwd(window)

    def _screenshot_mss(self, window: int) -> bytes:
        if _mss is None:
            raise RuntimeError("mss is not installed")
        geo = self._window_geometry(window)
        with _mss.mss() as sct:
            monitor = {
                "left": geo["x"],
                "top": geo["y"],
                "width": geo["w"],
                "height": geo["h"],
            }
            shot = sct.grab(monitor)
            return _mss_tools.to_png(shot.rgb, shot.size)  # type: ignore[union-attr]

    def _screenshot_xwd(self, window: int) -> bytes:
        """Fallback using xwd + convert (requires ImageMagick)."""
        xwd = subprocess.run(
            ["xwd", "-id", str(window), "-silent"],
            capture_output=True,
            check=True,
        )
        convert = subprocess.run(
            ["convert", "xwd:-", "png:-"],
            input=xwd.stdout,
            capture_output=True,
            check=True,
        )
        return convert.stdout

    def _window_geometry(self, window: int) -> dict[str, int]:
        if _XLIB and _xdisplay is not None:
            d = _xdisplay.Display()
            w = d.create_resource_object("window", window)
            geom = w.get_geometry()
            # translate to screen coords
            coord = w.translate_coords(d.screen().root, 0, 0)
            return {
                "x": coord.x,
                "y": coord.y,
                "w": geom.width,
                "h": geom.height,
            }
        # Fallback: parse xdotool getwindowgeometry
        result = _xdotool("getwindowgeometry", "--shell", str(window))
        geo: dict[str, int] = {}
        for line in result.stdout.splitlines():
            m = re.match(r"(\w+)=(\d+)", line)
            if m:
                geo[m.group(1).upper()] = int(m.group(2))
        return {
            "x": geo.get("X", 0),
            "y": geo.get("Y", 0),
            "w": geo.get("WIDTH", 0),
            "h": geo.get("HEIGHT", 0),
        }

    def get_window_info(self, window: int) -> dict:
        geo = self._window_geometry(window)
        name_result = _xdotool("getwindowname", str(window), check=False)
        title = name_result.stdout.strip() if name_result.returncode == 0 else ""
        return {"window_id": window, "title": title, **geo}
