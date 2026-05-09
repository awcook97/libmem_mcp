"""Input backend Protocol and GatedBackend allowlist enforcer.

``InputBackend`` is a structural protocol — any class that implements the
required methods qualifies without inheriting from it.

``GatedBackend`` wraps any backend and rejects any key press for a key that is
not in the ``allowed_keys`` frozenset provided at construction time.  This is
the single enforcement point; no code path in the server bypasses it.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class DisallowedKeyError(ValueError):
    """Raised when the gated backend is asked to press an undeclared key."""


@runtime_checkable
class InputBackend(Protocol):
    """Structural protocol for all platform input backends."""

    def find_window(self, pid: int, title_regex: str | None = None) -> int:
        """Return an opaque window handle for the process.

        Raises ``RuntimeError`` if no window is found or if more than one
        top-level window is owned by the PID and no ``title_regex`` is given.
        """
        ...

    def key_press(self, window: int, key: str) -> None:
        """Send a key-down event to *window*."""
        ...

    def key_release(self, window: int, key: str) -> None:
        """Send a key-up event to *window*."""
        ...

    def key_tap(self, window: int, key: str) -> None:
        """Press and release *key* with a short delay."""
        ...

    def type_text(self, window: int, text: str) -> None:
        """Type a string into *window* character-by-character."""
        ...

    def mouse_click(
        self, window: int, button: str, x: int, y: int, relative: bool = True
    ) -> None:
        """Click *button* (``"left"`` / ``"right"`` / ``"middle"``) at (x, y)."""
        ...

    def screenshot(self, window: int) -> bytes:
        """Capture just the target window and return PNG bytes."""
        ...

    def get_window_info(self, window: int) -> dict:
        """Return a dict with at least ``title``, ``x``, ``y``, ``w``, ``h``."""
        ...


class GatedBackend:
    """Wraps any InputBackend and enforces the per-target key allowlist.

    Every call that involves pressing a key is validated here before it
    reaches the underlying backend.  An undeclared key raises
    ``DisallowedKeyError`` — the wrapped backend never sees the call.
    """

    def __init__(self, backend: InputBackend, allowed_keys: frozenset[str]) -> None:
        self._backend = backend
        self._allowed = allowed_keys

    def _check(self, key: str) -> None:
        if key not in self._allowed:
            raise DisallowedKeyError(
                f"Key {key!r} is not in the allowed key set for this target. "
                "Add it to the keymap in your config file to enable it."
            )

    def find_window(self, pid: int, title_regex: str | None = None) -> int:
        return self._backend.find_window(pid, title_regex)

    def key_press(self, window: int, key: str) -> None:
        self._check(key)
        self._backend.key_press(window, key)

    def key_release(self, window: int, key: str) -> None:
        self._check(key)
        self._backend.key_release(window, key)

    def key_tap(self, window: int, key: str) -> None:
        self._check(key)
        self._backend.key_tap(window, key)

    def type_text(self, window: int, text: str) -> None:
        # Validate the whole string first so we never send a partial sequence.
        if text not in self._allowed:
            raise DisallowedKeyError(
                f"Text {text!r} is not in the allowed set for this target. "
                "Declare it as a macro text step in your config to enable it."
            )
        self._backend.type_text(window, text)

    def mouse_click(
        self, window: int, button: str, x: int, y: int, relative: bool = True
    ) -> None:
        # Mouse clicks are gated via macro declarations, not key names.
        # The server only invokes mouse_click when executing a declared macro step.
        self._backend.mouse_click(window, button, x, y, relative)

    def screenshot(self, window: int) -> bytes:
        return self._backend.screenshot(window)

    def get_window_info(self, window: int) -> dict:
        return self._backend.get_window_info(window)
