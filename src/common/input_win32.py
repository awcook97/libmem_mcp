"""Windows input + screenshot backend using pywin32.

Requires pywin32::

    uv add --optional gameinput-win32 pywin32

Key events use PostMessage (WM_KEYDOWN / WM_KEYUP) so they work on
unfocused windows.  Screenshots capture only the window's client area via
BitBlt/GetDC.
"""
from __future__ import annotations

import io
import re
import time
from typing import Any

# Pre-declare as Any so type checkers don't error on attribute access.
# At runtime, _WIN32 = False means none of these are called.
win32api:     Any
win32con:     Any
win32gui:     Any
win32process: Any
win32ui:      Any
Image:        Any

# win32 imports are conditional — module is importable on all platforms.
try:
    import win32api       # type: ignore[import]
    import win32con       # type: ignore[import]
    import win32gui       # type: ignore[import]
    import win32process   # type: ignore[import]
    import win32ui        # type: ignore[import]
    from PIL import Image  # type: ignore[import]
    _WIN32: bool = True
except ImportError:
    _WIN32 = False


# Minimal VK (virtual-key) mapping for common key names.
# Extend as needed; keys not listed fall back to ord(key[0].upper()).
_VK_MAP: dict[str, int] = {
    "Return": 0x0D, "Enter": 0x0D,
    "space": 0x20, "Space": 0x20,
    "Tab": 0x09,
    "BackSpace": 0x08, "Backspace": 0x08,
    "Escape": 0x1B, "Esc": 0x1B,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "Home": 0x24, "End": 0x23,
    "Prior": 0x21, "Page_Up": 0x21,   # xdotool names
    "Next": 0x22,  "Page_Down": 0x22,
    "Insert": 0x2D, "Delete": 0x2E,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "Num_9": 0x69, "Num_3": 0x63, "Num_5": 0x65,
    "Num_7": 0x67, "Num_1": 0x61,
    "shift": 0x10, "Shift_L": 0x10, "Shift_R": 0x10,
    "ctrl":  0x11, "Control_L": 0x11, "Control_R": 0x11,
    "alt":   0x12, "Alt_L": 0x12, "Alt_R": 0x12,
}

_TAP_DELAY = 0.05


def _vk(key: str) -> int:
    if key in _VK_MAP:
        return _VK_MAP[key]
    if len(key) == 1:
        return ord(key.upper())
    raise ValueError(f"Unknown key name for Win32 backend: {key!r}")


def _make_lparam(key: str, transition_state: int, prev_state: int) -> int:
    """Build lParam for WM_KEYDOWN/WM_KEYUP."""
    vk = _vk(key)
    scan = win32api.MapVirtualKey(vk, 0)
    return (
        (1)                          # repeat count
        | (scan << 16)               # scan code
        | (transition_state << 31)   # 0=down, 1=up
        | (prev_state << 30)         # 0=was-up, 1=was-down
    )


class Win32Backend:
    """Win32 backend: PostMessage for keys, BitBlt for screenshots."""

    def find_window(self, pid: int, title_regex: str | None = None) -> int:
        """Return an HWND for the process."""
        if not _WIN32:
            raise RuntimeError("pywin32 is not installed")

        matches: list[int] = []

        def _cb(hwnd: int, _: Any) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid != pid:
                return
            if title_regex:
                title = win32gui.GetWindowText(hwnd)
                if not re.search(title_regex, title):
                    return
            matches.append(hwnd)

        win32gui.EnumWindows(_cb, None)

        if not matches:
            raise RuntimeError(
                f"No visible Win32 window found for PID {pid}"
                + (f" matching {title_regex!r}" if title_regex else "")
            )
        if len(matches) > 1 and title_regex is None:
            raise RuntimeError(
                f"PID {pid} owns {len(matches)} windows; "
                "set 'window_title_regex' in your config to select one"
            )
        return matches[0]

    def key_press(self, window: int, key: str) -> None:
        vk = _vk(key)
        lp = _make_lparam(key, 0, 0)
        win32api.PostMessage(window, win32con.WM_KEYDOWN, vk, lp)

    def key_release(self, window: int, key: str) -> None:
        vk = _vk(key)
        lp = _make_lparam(key, 1, 1)
        win32api.PostMessage(window, win32con.WM_KEYUP, vk, lp)

    def key_tap(self, window: int, key: str) -> None:
        self.key_press(window, key)
        time.sleep(_TAP_DELAY)
        self.key_release(window, key)

    def type_text(self, window: int, text: str) -> None:
        for ch in text:
            win32api.PostMessage(window, win32con.WM_CHAR, ord(ch), 0)
            time.sleep(0.02)

    def mouse_click(
        self, window: int, button: str, x: int, y: int, relative: bool = True
    ) -> None:
        if relative:
            rect = win32gui.GetClientRect(window)
            # rect is (left, top, right, bottom) in client coords
            cx, cy = x, y
        else:
            cx, cy = win32gui.ScreenToClient(window, (x, y))

        lparam = (cy << 16) | (cx & 0xFFFF)
        down_msg, up_msg = {
            "left":   (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP),
            "right":  (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP),
            "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP),
        }.get(button.lower(), (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP))
        win32api.PostMessage(window, down_msg, 0, lparam)
        time.sleep(_TAP_DELAY)
        win32api.PostMessage(window, up_msg, 0, lparam)

    def screenshot(self, window: int) -> bytes:
        if not _WIN32:
            raise RuntimeError("pywin32 is not installed")

        left, top, right, bottom = win32gui.GetClientRect(window)
        w = right - left
        h = bottom - top

        hwnd_dc = win32gui.GetWindowDC(window)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        save_dc.BitBlt((0, 0), (w, h), mfc_dc, (left, top), win32con.SRCCOPY)

        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)

        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        )

        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(window, hwnd_dc)
        win32gui.DeleteObject(bmp.GetHandle())

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def get_window_info(self, window: int) -> dict:
        title = win32gui.GetWindowText(window)
        rect = win32gui.GetWindowRect(window)
        x, y, r, b = rect
        return {
            "window_id": window,
            "title": title,
            "x": x,
            "y": y,
            "w": r - x,
            "h": b - y,
        }
