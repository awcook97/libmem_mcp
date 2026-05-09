"""CFG_Game-style keymap importer.

Parses lines in the format::

    [ACTION] Nrm:Key Alt:Key

and emits a JSON keymap dict suitable for pasting into ``gameinput.config.json``.

CLI usage (stdout only — never writes to the config):

    uv run gameinput-mcp import-keymap path/to/game.cfg
    uv run gameinput-mcp import-keymap path/to/game.cfg --keymap-name GAME_DEFAULT
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_LINE_RE = re.compile(
    r"^\[(?P<action>[^\]]+)\]\s+"
    r"Nrm:(?P<nrm>\S+)\s+"
    r"Alt:(?P<alt>\S+)",
    re.IGNORECASE,
)


def _coerce(val: str) -> str | None:
    return None if val.lower() == "clear" else val


def parse_game_keymap(text: str) -> dict[str, dict[str, str | None]]:
    """Parse game-style keymap text and return a keymap dict.

    Each entry has the shape ``{"nrm": str|null, "alt": str|null}``.
    Lines that don't match the pattern are silently skipped.
    """
    result: dict[str, dict[str, str | None]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        result[m.group("action")] = {
            "nrm": _coerce(m.group("nrm")),
            "alt": _coerce(m.group("alt")),
        }
    return result


def import_keymap_cli(args: list[str]) -> None:
    """Entry point for ``gameinput-mcp import-keymap``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="gameinput-mcp import-keymap",
        description=(
            "Parse an game-style keymap file and print a JSON keymap block "
            "suitable for pasting into gameinput.config.json."
        ),
    )
    parser.add_argument("file", help="Path to the keymap file")
    parser.add_argument(
        "--keymap-name",
        default="IMPORTED",
        help="Name for the keymap key in output JSON (default: IMPORTED)",
    )
    ns = parser.parse_args(args)

    path = Path(ns.file)
    if not path.is_file():
        sys.exit(f"File not found: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    keymap = parse_game_keymap(text)

    output = {"keymaps": {ns.keymap_name: keymap}}
    print(json.dumps(output, indent=2))
