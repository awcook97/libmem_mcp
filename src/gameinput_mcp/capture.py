"""Screenshot capture pipeline for gameinput-mcp.

Every action that sends input calls ``CaptureSession`` which snapshots:
  - immediately before the action (pre)
  - 0.3 s after (t0_3s)
  - 3.0 s after (t3s)

All three PNG blobs are held in memory and returned inline as base64.
If a tempfile path is needed (e.g. for a read_screenshot fallback tool),
call ``write_temp()`` on a ``Capture`` to spill it to disk.
"""
from __future__ import annotations

import asyncio
import base64
import io
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Capture:
    """One PNG screenshot."""
    label: str        # "pre", "t0_3s", "t3s"
    png: bytes

    def as_base64(self) -> str:
        return base64.b64encode(self.png).decode("ascii")

    def write_temp(self) -> Path:
        """Write PNG to a temp file and return its path (caller owns cleanup)."""
        f = tempfile.NamedTemporaryFile(
            suffix=".png", prefix=f"gameinput_{self.label}_", delete=False
        )
        f.write(self.png)
        f.close()
        return Path(f.name)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "mime": "image/png",
            "base64": self.as_base64(),
        }


@dataclass
class CaptureSet:
    pre: Capture
    t0_3s: Capture
    t3s: Capture

    def to_dict(self) -> dict:
        return {
            "pre": self.pre.to_dict(),
            "t0_3s": self.t0_3s.to_dict(),
            "t3s": self.t3s.to_dict(),
        }


async def capture_three(
    shoot: Callable[[], bytes],
) -> CaptureSet:
    """Take the pre-shot, then schedule and await the two post-shots.

    ``shoot`` is a zero-argument callable that returns PNG bytes (should be
    a bound method on the gated backend, already holding its window handle).
    It is called in the default executor to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()

    def _snap() -> bytes:
        return shoot()

    pre_png = await loop.run_in_executor(None, _snap)
    pre = Capture("pre", pre_png)

    async def _delayed(delay: float, label: str) -> Capture:
        await asyncio.sleep(delay)
        png = await loop.run_in_executor(None, _snap)
        return Capture(label, png)

    t0_3s, t3s = await asyncio.gather(
        _delayed(0.3, "t0_3s"),
        _delayed(3.0, "t3s"),
    )

    return CaptureSet(pre=pre, t0_3s=t0_3s, t3s=t3s)


async def capture_single(shoot: Callable[[], bytes]) -> Capture:
    """Single snapshot (for the standalone screenshot tool)."""
    loop = asyncio.get_running_loop()
    png = await loop.run_in_executor(None, shoot)
    return Capture("screenshot", png)
