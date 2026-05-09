"""Read-only config loader for gameinput-mcp.

Loads a single JSON file describing target processes, keymaps, and macros.
Never writes to the file; any attempt by the server to mutate config state
must go through this module, which provides no mutation API.

Resolution order (first hit wins):
1. Explicit path passed to ``load_config(path=...)``.
2. ``GAMEINPUT_MCP_CONFIG`` environment variable.
3. Walk up from CWD looking for ``gameinput.config.json`` or
   ``.gameinput/config.json``.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyEntry:
    """One keymap entry: normal binding and alt binding (either may be None)."""
    nrm: str | None   # key name, or None/"clear" = unbound
    alt: str | None


@dataclass(frozen=True)
class MacroStep:
    type: str   # "key" | "text" | "delay" | "mouse" | "action"
    value: str | int | float | dict | None  # type-dependent payload

    VALID_TYPES = frozenset({"key", "text", "delay", "mouse", "action"})

    def __post_init__(self) -> None:
        if self.type not in self.VALID_TYPES:
            raise ValueError(f"Unknown macro step type: {self.type!r}")


@dataclass(frozen=True)
class Target:
    name: str
    match_process_name: str | None
    match_pid: int | None
    window_title_regex: str | None
    platform: str          # "x11" | "win32" | "auto"
    keymap_name: str
    macro_names: frozenset[str]
    # Populated during validation — all physical key strings reachable for
    # this target (across both nrm and alt bindings).
    allowed_keys: frozenset[str]


@dataclass(frozen=True)
class Config:
    targets: dict[str, Target]
    keymaps: dict[str, dict[str, KeyEntry]]   # keymap_name -> {ACTION: KeyEntry}
    macros: dict[str, list[MacroStep]]


# ---------------------------------------------------------------------------
# Config file resolution
# ---------------------------------------------------------------------------

_SEARCH_NAMES = ("gameinput.config.json", ".gameinput/config.json")


def _find_config_in_tree(start: Path) -> Path | None:
    """Walk up the directory tree from *start* looking for a config file."""
    current = start.resolve()
    while True:
        for name in _SEARCH_NAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Return the config file path, or raise ``FileNotFoundError``."""
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p

    env = os.environ.get("GAMEINPUT_MCP_CONFIG")
    if env:
        p = Path(env)
        if not p.is_file():
            raise FileNotFoundError(
                f"GAMEINPUT_MCP_CONFIG points to missing file: {p}"
            )
        return p

    found = _find_config_in_tree(Path.cwd())
    if found:
        return found

    raise FileNotFoundError(
        "No gameinput config found. Provide --config, set "
        "GAMEINPUT_MCP_CONFIG, or place gameinput.config.json in (or above) "
        "the working directory."
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_key_entry(raw: object, action: str, km_name: str) -> KeyEntry:
    if raw is None:
        return KeyEntry(nrm=None, alt=None)
    if not isinstance(raw, dict):
        raise ValueError(
            f"keymap {km_name!r} action {action!r}: expected dict or null, "
            f"got {type(raw).__name__}"
        )
    def _coerce(v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return None if s.lower() == "clear" else s or None

    return KeyEntry(nrm=_coerce(raw.get("nrm")), alt=_coerce(raw.get("alt")))


def _parse_macro_step(raw: object, macro_name: str, idx: int) -> MacroStep:
    if not isinstance(raw, dict):
        raise ValueError(
            f"macro {macro_name!r} step {idx}: expected dict, "
            f"got {type(raw).__name__}"
        )
    t = raw.get("type")
    if not isinstance(t, str):
        raise ValueError(f"macro {macro_name!r} step {idx}: missing 'type'")
    v = raw.get("value")
    if v is None and t not in ("delay",):
        raise ValueError(f"macro {macro_name!r} step {idx}: missing 'value'")
    return MacroStep(type=t, value=v)  # __post_init__ validates type


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _build_allowed_keys(
    keymap: dict[str, KeyEntry],
    macros_for_target: list[list[MacroStep]],
    all_keymaps: dict[str, dict[str, KeyEntry]],
) -> frozenset[str]:
    """Collect every physical key this target is allowed to press."""
    keys: set[str] = set()
    for entry in keymap.values():
        if entry.nrm:
            keys.add(entry.nrm)
        if entry.alt:
            keys.add(entry.alt)
    # Keys reachable through macro steps of type "text" are the individual
    # characters; we add them so the gated backend can validate them too.
    for steps in macros_for_target:
        for step in steps:
            if step.type == "key" and isinstance(step.value, str):
                keys.add(step.value)
            elif step.type == "text" and isinstance(step.value, str):
                # Each char in the text must be pressable.  We store the
                # whole string here; the gate will decompose it at runtime.
                keys.add(step.value)
    return frozenset(keys)


def _validate(
    raw_targets: dict,
    keymaps: dict[str, dict[str, KeyEntry]],
    macros: dict[str, list[MacroStep]],
) -> dict[str, Target]:
    targets: dict[str, Target] = {}
    for t_name, t_raw in raw_targets.items():
        if not isinstance(t_raw, dict):
            raise ValueError(f"target {t_name!r} must be a JSON object")

        km_name = t_raw.get("keymap")
        if not isinstance(km_name, str):
            raise ValueError(f"target {t_name!r}: 'keymap' must be a string")
        if km_name not in keymaps:
            raise ValueError(
                f"target {t_name!r} references keymap {km_name!r} "
                "which is not defined in 'keymaps'"
            )

        macro_names_raw: list = t_raw.get("macros", [])
        if not isinstance(macro_names_raw, list):
            raise ValueError(f"target {t_name!r}: 'macros' must be a list")
        macro_names: frozenset[str] = frozenset(macro_names_raw)
        for mn in macro_names:
            if mn not in macros:
                raise ValueError(
                    f"target {t_name!r} references macro {mn!r} "
                    "which is not defined in 'macros'"
                )
            # Verify action-type steps reference valid keymap entries.
            for idx, step in enumerate(macros[mn]):
                if step.type == "action":
                    if not isinstance(step.value, str):
                        raise ValueError(
                            f"macro {mn!r} step {idx}: action value must be string"
                        )
                    if step.value not in keymaps[km_name]:
                        raise ValueError(
                            f"macro {mn!r} step {idx}: action {step.value!r} "
                            f"not in keymap {km_name!r}"
                        )

        match_raw = t_raw.get("match", {})
        proc_name = match_raw.get("name") if isinstance(match_raw, dict) else None
        pid_raw = match_raw.get("pid") if isinstance(match_raw, dict) else None
        pid = int(pid_raw) if pid_raw is not None else None

        platform = t_raw.get("platform", "auto")
        if platform not in ("x11", "win32", "auto"):
            raise ValueError(
                f"target {t_name!r}: platform must be 'x11', 'win32', or 'auto'"
            )

        macro_steps_for_target = [macros[mn] for mn in macro_names]
        allowed_keys = _build_allowed_keys(
            keymaps[km_name], macro_steps_for_target, keymaps
        )

        targets[t_name] = Target(
            name=t_name,
            match_process_name=proc_name,
            match_pid=pid,
            window_title_regex=t_raw.get("window_title_regex"),
            platform=platform,
            keymap_name=km_name,
            macro_names=macro_names,
            allowed_keys=allowed_keys,
        )
    return targets


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_config(path: str | Path | None = None) -> Config:
    """Load, parse, and validate the gameinput config file.

    Raises ``FileNotFoundError`` if no file is found, ``ValueError`` for
    schema or reference errors.  Never writes anything.
    """
    config_path = resolve_config_path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a JSON object")

    # Parse keymaps first (targets reference them).
    raw_keymaps: dict = raw.get("keymaps", {})
    keymaps: dict[str, dict[str, KeyEntry]] = {}
    for km_name, km_raw in raw_keymaps.items():
        if not isinstance(km_raw, dict):
            raise ValueError(f"keymap {km_name!r} must be a JSON object")
        keymaps[km_name] = {
            action: _parse_key_entry(entry, action, km_name)
            for action, entry in km_raw.items()
        }

    # Parse macros.
    raw_macros: dict = raw.get("macros", {})
    macros: dict[str, list[MacroStep]] = {}
    for m_name, m_raw in raw_macros.items():
        if not isinstance(m_raw, list):
            raise ValueError(f"macro {m_name!r} must be a JSON array")
        macros[m_name] = [
            _parse_macro_step(step, m_name, i) for i, step in enumerate(m_raw)
        ]

    # Parse and validate targets.
    raw_targets: dict = raw.get("targets", {})
    targets = _validate(raw_targets, keymaps, macros)

    return Config(targets=targets, keymaps=keymaps, macros=macros)
