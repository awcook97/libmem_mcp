from __future__ import annotations

import base64
import functools
import itertools
import json
import os
import pathlib
import time
from collections.abc import Iterable
from typing import Any, cast

import libmem
from mcp.server.fastmcp import FastMCP

from common.log import MemLogger

# ── autologger setup ─────────────────────────────────────────────────────────
_LOG_DIR = pathlib.Path(os.getenv("LIBMEM_MCP_LOG_DIR", str(pathlib.Path(__file__).parent.parent.parent / "output")))
_mlog = MemLogger("libmem_mcp", _LOG_DIR, level="trace")
_logger = _mlog.get("server")
_logger.info("libmem-mcp server started, logging to %s", _mlog.log_file)


def _autolog(fn: Any) -> Any:
    """Wrap an MCP tool function to log every call and result."""
    @functools.wraps(fn)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        name = fn.__name__
        arg_str = ", ".join(
            [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        )
        _logger.trace(">> %s(%s)", name, arg_str)
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            _logger.error("!! %s raised %s: %s", name, type(exc).__name__, exc)
            raise
        elapsed = (time.monotonic() - t0) * 1000
        # Summarise large results so the log stays readable
        try:
            summary = json.dumps(result, default=str)
            if len(summary) > 500:
                summary = summary[:500] + f"... [{len(summary)} chars total]"
        except Exception:
            summary = repr(result)[:500]
        _logger.debug("<< %s  (%.1f ms)  %s", name, elapsed, summary)
        return result
    return _wrapper

MAX_READ_BYTES = int(os.getenv("LIBMEM_MCP_MAX_READ_BYTES", str(1024 * 1024)))


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Mutating libmem APIs (writes, allocation, hooking, protection changes,
# module load/unload, vtable hooks) are only registered when this flag is set.
# By default the server stays a read-only inspector.
WRITES_ENABLED = _env_flag("LIBMEM_MCP_ENABLE_WRITES")

READONLY_LIBMEM_FUNCTIONS = [
    "assemble",
    "assemble_ex",
    "code_length",
    "code_length_ex",
    "data_scan",
    "data_scan_ex",
    "deep_pointer",
    "deep_pointer_ex",
    "demangle_symbol",
    "disassemble",
    "disassemble_ex",
    "enum_modules",
    "enum_modules_ex",
    "enum_processes",
    "enum_segments",
    "enum_segments_ex",
    "enum_symbols",
    "enum_symbols_demangled",
    "enum_threads",
    "enum_threads_ex",
    "find_module",
    "find_module_ex",
    "find_process",
    "find_segment",
    "find_segment_ex",
    "find_symbol_address",
    "find_symbol_address_demangled",
    "get_architecture",
    "get_bits",
    "get_command_line",
    "get_process",
    "get_process_ex",
    "get_system_bits",
    "get_thread",
    "get_thread_ex",
    "get_thread_process",
    "is_process_alive",
    "pattern_scan",
    "pattern_scan_ex",
    "read_memory",
    "read_memory_ex",
    "sig_scan",
    "sig_scan_ex",
]

# The mutating tools registered when WRITES_ENABLED are listed by libmem_mcp_info,
# derived from the actual _MUTATING_TOOLS registration list (defined further down)
# so the reported names can never drift from what is really exposed.

# Kept for backwards compatibility with anything reading the old name.
EXPOSED_LIBMEM_FUNCTIONS = READONLY_LIBMEM_FUNCTIONS

mcp = FastMCP(
    "libmem-mcp",
    instructions=(
        "MCP wrapper for libmem. Always exposes read-only helpers: process, "
        "thread, module, symbol, segment, memory-read, scan, pointer, "
        "disassembly, and assembly. Mutating libmem APIs (memory writes, "
        "set_memory, alloc/free, protection changes, code hooks, module "
        "load/unload, and Vmt vtable hooks) are gated behind the "
        "LIBMEM_MCP_ENABLE_WRITES environment variable and are only registered "
        "when it is set. Call libmem_mcp_info to see which tools are active and "
        "the accepted address/byte/protection input formats."
    ),
)


def _as_int(value: int | str, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.replace("_", ""), 0)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer or base-prefixed integer string") from exc
    raise TypeError(f"{name} must be an integer or string")


def _as_non_negative_int(value: int | str, name: str) -> int:
    number = _as_int(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _as_int_list(values: Iterable[int | str], name: str) -> list[int]:
    return [_as_int(value, f"{name}[{index}]") for index, value in enumerate(values)]


def _check_read_size(value: int | str, name: str = "size") -> int:
    size = _as_non_negative_int(value, name)
    if size > MAX_READ_BYTES:
        raise ValueError(
            f"{name} exceeds LIBMEM_MCP_MAX_READ_BYTES ({MAX_READ_BYTES}). "
            "Set that environment variable higher if this read is intentional."
        )
    return size


def _hex(value: int) -> str:
    return f"0x{value:x}"


def _serialize_bytes(data: bytes | bytearray) -> dict[str, Any]:
    raw = bytes(data)
    return {
        "size": len(raw),
        "hex": raw.hex(),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _decode_bytes(data: str, encoding: str) -> bytearray:
    normalized = encoding.lower().replace("_", "-")
    if normalized == "hex":
        compact = data.replace(" ", "").replace("\n", "").replace("\t", "").replace("\\x", "")
        if compact.startswith("0x"):
            compact = compact[2:]
        return bytearray.fromhex(compact)
    if normalized == "base64":
        return bytearray(base64.b64decode(data, validate=True))
    if normalized in {"utf-8", "utf8", "text"}:
        return bytearray(data.encode("utf-8"))
    raise ValueError("encoding must be one of: hex, base64, utf-8")


def _serialize_process(process: Any) -> dict[str, Any] | None:
    if process is None:
        return None
    return {
        "pid": process.pid,
        "ppid": process.ppid,
        "arch": str(process.arch),
        "bits": process.bits,
        "start_time": process.start_time,
        "path": process.path,
        "name": process.name,
    }


def _serialize_thread(thread: Any) -> dict[str, Any] | None:
    if thread is None:
        return None
    return {
        "tid": thread.tid,
        "owner_pid": thread.owner_pid,
    }


def _serialize_module(module: Any) -> dict[str, Any] | None:
    if module is None:
        return None
    return {
        "base": module.base,
        "base_hex": _hex(module.base),
        "end": module.end,
        "end_hex": _hex(module.end),
        "size": module.size,
        "size_hex": _hex(module.size),
        "path": module.path,
        "name": module.name,
    }


def _serialize_symbol(symbol: Any) -> dict[str, Any] | None:
    if symbol is None:
        return None
    return {
        "address": symbol.address,
        "address_hex": _hex(symbol.address),
        "name": symbol.name,
    }


def _serialize_segment(segment: Any) -> dict[str, Any] | None:
    if segment is None:
        return None
    return {
        "base": segment.base,
        "base_hex": _hex(segment.base),
        "end": segment.end,
        "end_hex": _hex(segment.end),
        "size": segment.size,
        "size_hex": _hex(segment.size),
        "prot": str(segment.prot),
    }


def _serialize_instruction(instruction: Any) -> dict[str, Any] | None:
    if instruction is None:
        return None
    return {
        "address": instruction.address,
        "address_hex": _hex(instruction.address),
        "size": instruction.size,
        "mnemonic": instruction.mnemonic,
        "op_str": instruction.op_str,
        "bytes": _serialize_bytes(instruction.bytes),
    }


def _serialize_address(address: int | None) -> dict[str, Any] | None:
    if address is None:
        return None
    return {
        "address": address,
        "address_hex": _hex(address),
    }


def _resolve_process(pid: int | str | None) -> Any:
    if pid is None:
        process = libmem.get_process()
        label = "current process"
    else:
        process_id = _as_non_negative_int(pid, "pid")
        process = libmem.get_process_ex(process_id)
        label = f"pid {process_id}"
    if process is None:
        raise ValueError(f"Could not resolve {label}")
    return process


def _resolve_thread(tid: int | str, pid: int | str | None = None) -> Any:
    thread_id = _as_non_negative_int(tid, "tid")
    if pid is None:
        threads = libmem.enum_threads()
    else:
        threads = libmem.enum_threads_ex(_resolve_process(pid))
    for thread in threads or []:
        if thread.tid == thread_id:
            return thread
    if pid is None:
        raise ValueError(f"Could not find thread {thread_id} in the current process")
    raise ValueError(f"Could not find thread {thread_id} in process {_as_int(pid, 'pid')}")


def _module_matches(
    module: Any,
    module_name: str | None,
    module_base: int | str | None,
    module_path: str | None,
) -> bool:
    if module_name is not None and module.name != module_name:
        return False
    if module_path is not None and module.path != module_path:
        return False
    if module_base is not None and module.base != _as_non_negative_int(module_base, "module_base"):
        return False
    return True


def _resolve_module(
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
    pid: int | str | None = None,
) -> Any:
    if module_name is None and module_base is None and module_path is None:
        raise ValueError("Provide at least one of module_name, module_base, or module_path")

    if module_name is not None and module_base is None and module_path is None:
        module = libmem.find_module_ex(_resolve_process(pid), module_name) if pid is not None else libmem.find_module(module_name)
        if module is not None:
            return module

    modules = libmem.enum_modules_ex(_resolve_process(pid)) if pid is not None else libmem.enum_modules()
    for module in modules or []:
        if _module_matches(module, module_name, module_base, module_path):
            return module

    target = ", ".join(
        part
        for part in (
            f"name={module_name!r}" if module_name is not None else "",
            f"base={module_base!r}" if module_base is not None else "",
            f"path={module_path!r}" if module_path is not None else "",
        )
        if part
    )
    scope = "current process" if pid is None else f"pid {_as_int(pid, 'pid')}"
    raise ValueError(f"Could not find module ({target}) in {scope}")


def _resolve_arch(arch: str) -> Any:
    normalized = arch.upper().replace("-", "_")
    candidates = [normalized]
    if normalized.startswith("LM_ARCH_"):
        candidates.append(normalized.removeprefix("LM_"))
    elif normalized.startswith("ARCH_"):
        candidates.append(f"LM_{normalized}")
    else:
        candidates.extend([f"ARCH_{normalized}", f"LM_ARCH_{normalized}"])

    for candidate in candidates:
        public_name = candidate.removeprefix("LM_")
        if hasattr(libmem, public_name):
            return getattr(libmem, public_name)
    supported = sorted(name for name in dir(libmem) if name.startswith("ARCH_"))
    raise ValueError(f"Unknown architecture {arch!r}. Supported values: {', '.join(supported)}")


def _resolve_prot(prot: str) -> Any:
    """Resolve a memory-protection value from rwx letters or a PROT_* name.

    Accepts any case/order and optional ``PROT_``/``LM_PROT_`` prefixes, e.g.
    ``"rw"``, ``"rwx"``, ``"xr"``, ``"PROT_RW"``, ``"LM_PROT_XRW"``.
    """
    raw = prot.upper().replace("-", "").replace("_", "")
    if raw.startswith("LMPROT"):
        raw = raw[len("LMPROT"):]
    elif raw.startswith("PROT"):
        raw = raw[len("PROT"):]
    letters = set(raw)
    valid = {"R", "W", "X"}
    if not letters or not letters <= valid:
        raise ValueError(
            f"Unknown protection {prot!r}. Use a combination of r/w/x "
            "(e.g. 'r', 'rw', 'rwx') or a name such as PROT_XRW."
        )
    # libmem orders the constant names X, then R, then W (PROT_XR, PROT_XRW, ...).
    name = "PROT_" + "".join(letter for letter in "XRW" if letter in letters)
    return getattr(libmem, name)


def _serialize_prot(prot: Any) -> dict[str, Any] | None:
    if prot is None:
        return None
    text = str(prot)
    return {
        "protection": text,
        "short": text.removeprefix("LM_PROT_").removeprefix("PROT_"),
    }


@mcp.tool()
def libmem_mcp_info() -> dict[str, Any]:
    """List the libmem APIs this MCP exposes and whether mutating tools are enabled."""
    return {
        "readonly_functions": READONLY_LIBMEM_FUNCTIONS,
        "mutating_functions": [fn.__name__ for fn in _MUTATING_TOOLS],
        "writes_enabled": WRITES_ENABLED,
        "writes_enabled_note": (
            "Mutating tools (writes, alloc/free, hooks, protection changes, "
            "module load/unload, vmt_*) are registered only when the "
            "LIBMEM_MCP_ENABLE_WRITES environment variable is set. They are "
            + ("ENABLED." if WRITES_ENABLED else "NOT registered in this session.")
        ),
        "max_read_bytes": MAX_READ_BYTES,
        "byte_input_encodings": ["hex", "base64", "utf-8"],
        "protection_inputs": "Protection parameters accept r/w/x combinations such as 'rw' or 'rwx', or names like PROT_XRW.",
        "address_inputs": "Address parameters accept integers or base-prefixed strings such as 0x7ffdeadbeef.",
    }


@mcp.tool()
def enum_processes() -> list[dict[str, Any]] | None:
    """Lists all current living processes."""
    processes = libmem.enum_processes()
    if processes is None:
        return None
    return [cast(dict[str, Any], _serialize_process(process)) for process in processes if process is not None]


@mcp.tool()
def get_process() -> dict[str, Any] | None:
    """Gets information about the MCP server process."""
    return _serialize_process(libmem.get_process())


@mcp.tool()
def get_process_ex(pid: int | str) -> dict[str, Any] | None:
    """Gets information about a process from a process ID."""
    return _serialize_process(libmem.get_process_ex(_as_non_negative_int(pid, "pid")))


@mcp.tool()
def get_command_line(pid: int | str | None = None) -> list[str] | None:
    """Retrieves command line arguments for a process. Omit pid for the MCP server process."""
    command_line = libmem.get_command_line(_resolve_process(pid))
    if command_line is None:
        return None
    return list(command_line)


@mcp.tool()
def find_process(process_name: str) -> dict[str, Any] | None:
    """Searches for an existing process by name."""
    return _serialize_process(libmem.find_process(process_name))


@mcp.tool()
def is_process_alive(pid: int | str) -> bool:
    """Checks if a process is alive."""
    process = libmem.get_process_ex(_as_non_negative_int(pid, "pid"))
    return False if process is None else libmem.is_process_alive(process)


@mcp.tool()
def get_bits() -> int:
    """Gets the bit width of the MCP server process."""
    return libmem.get_bits()


@mcp.tool()
def get_system_bits() -> int:
    """Gets the bit width of the operating system."""
    return libmem.get_system_bits()


@mcp.tool()
def enum_threads() -> list[dict[str, Any]] | None:
    """Lists all threads from the MCP server process."""
    threads = libmem.enum_threads()
    if threads is None:
        return None
    return [cast(dict[str, Any], _serialize_thread(thread)) for thread in threads if thread is not None]


@mcp.tool()
def enum_threads_ex(pid: int | str) -> list[dict[str, Any]] | None:
    """Lists all threads from a remote process."""
    threads = libmem.enum_threads_ex(_resolve_process(pid))
    if threads is None:
        return None
    return [cast(dict[str, Any], _serialize_thread(thread)) for thread in threads if thread is not None]


@mcp.tool()
def get_thread() -> dict[str, Any] | None:
    """Gets information about the MCP server thread."""
    return _serialize_thread(libmem.get_thread())


@mcp.tool()
def get_thread_ex(pid: int | str) -> dict[str, Any] | None:
    """Gets information about a remote process thread."""
    return _serialize_thread(libmem.get_thread_ex(_resolve_process(pid)))


@mcp.tool()
def get_thread_process(tid: int | str, pid: int | str | None = None) -> dict[str, Any] | None:
    """Gets information about a process from a thread ID. Provide pid to search a remote process."""
    return _serialize_process(libmem.get_thread_process(_resolve_thread(tid, pid)))


@mcp.tool()
def enum_modules() -> list[dict[str, Any]] | None:
    """Lists all modules from the MCP server process."""
    modules = libmem.enum_modules()
    if modules is None:
        return None
    return [cast(dict[str, Any], _serialize_module(module)) for module in modules if module is not None]


@mcp.tool()
def enum_modules_ex(pid: int | str) -> list[dict[str, Any]] | None:
    """Lists all modules from a remote process."""
    modules = libmem.enum_modules_ex(_resolve_process(pid))
    if modules is None:
        return None
    return [cast(dict[str, Any], _serialize_module(module)) for module in modules if module is not None]


@mcp.tool()
def find_module(module_name: str) -> dict[str, Any] | None:
    """Searches for a module in the MCP server process."""
    return _serialize_module(libmem.find_module(module_name))


@mcp.tool()
def find_module_ex(pid: int | str, module_name: str) -> dict[str, Any] | None:
    """Searches for a module in a remote process."""
    return _serialize_module(libmem.find_module_ex(_resolve_process(pid), module_name))


@mcp.tool()
def enum_symbols(
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
    pid: int | str | None = None,
) -> list[dict[str, Any]] | None:
    """Lists all symbols from a module. Identify the module by name, base, or path; provide pid for a remote process."""
    symbols = libmem.enum_symbols(_resolve_module(module_name, module_base, module_path, pid))
    if symbols is None:
        return None
    return [cast(dict[str, Any], _serialize_symbol(symbol)) for symbol in symbols if symbol is not None]


@mcp.tool()
def find_symbol_address(
    symbol_name: str,
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
    pid: int | str | None = None,
) -> dict[str, Any] | None:
    """Searches for a symbol address in a module."""
    address = libmem.find_symbol_address(
        _resolve_module(module_name, module_base, module_path, pid),
        symbol_name,
    )
    return _serialize_address(address)


@mcp.tool()
def demangle_symbol(mangled_symbol: str) -> str | None:
    """Demangles a mangled symbol name."""
    return libmem.demangle_symbol(mangled_symbol)


@mcp.tool()
def enum_symbols_demangled(
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
    pid: int | str | None = None,
) -> list[dict[str, Any]] | None:
    """Lists all demangled symbols from a module."""
    symbols = libmem.enum_symbols_demangled(_resolve_module(module_name, module_base, module_path, pid))
    if symbols is None:
        return None
    return [cast(dict[str, Any], _serialize_symbol(symbol)) for symbol in symbols if symbol is not None]


@mcp.tool()
def find_symbol_address_demangled(
    demangled_symbol_name: str,
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
    pid: int | str | None = None,
) -> dict[str, Any] | None:
    """Searches for a demangled symbol address in a module."""
    address = libmem.find_symbol_address_demangled(
        _resolve_module(module_name, module_base, module_path, pid),
        demangled_symbol_name,
    )
    return _serialize_address(address)


@mcp.tool()
def enum_segments() -> list[dict[str, Any]] | None:
    """Lists all memory segments from the MCP server process."""
    segments = libmem.enum_segments()
    if segments is None:
        return None
    return [cast(dict[str, Any], _serialize_segment(segment)) for segment in segments if segment is not None]


@mcp.tool()
def enum_segments_ex(pid: int | str) -> list[dict[str, Any]] | None:
    """Lists all memory segments from a remote process."""
    segments = libmem.enum_segments_ex(_resolve_process(pid))
    if segments is None:
        return None
    return [cast(dict[str, Any], _serialize_segment(segment)) for segment in segments if segment is not None]


@mcp.tool()
def find_segment(address: int | str) -> dict[str, Any] | None:
    """Gets information about the segment of an address in the MCP server process."""
    return _serialize_segment(libmem.find_segment(_as_non_negative_int(address, "address")))


@mcp.tool()
def find_segment_ex(pid: int | str, address: int | str) -> dict[str, Any] | None:
    """Gets information about the segment of an address in a remote process."""
    return _serialize_segment(libmem.find_segment_ex(_resolve_process(pid), _as_non_negative_int(address, "address")))


@mcp.tool()
def read_memory(src: int | str, size: int | str) -> dict[str, Any] | None:
    """Reads memory from the MCP server process and returns hex/base64 bytes."""
    data = libmem.read_memory(_as_non_negative_int(src, "src"), _check_read_size(size))
    if data is None:
        return None
    return _serialize_bytes(data)


@mcp.tool()
def read_memory_ex(pid: int | str, source: int | str, size: int | str) -> dict[str, Any] | None:
    """Reads memory from a remote process and returns hex/base64 bytes."""
    data = libmem.read_memory_ex(
        _resolve_process(pid),
        _as_non_negative_int(source, "source"),
        _check_read_size(size),
    )
    if data is None:
        return None
    return _serialize_bytes(data)


@mcp.tool()
def deep_pointer(base: int | str, offsets: list[int | str]) -> dict[str, Any] | None:
    """Dereferences a deep pointer in the MCP server process."""
    address = libmem.deep_pointer(_as_non_negative_int(base, "base"), _as_int_list(offsets, "offsets"))
    return _serialize_address(address)


@mcp.tool()
def deep_pointer_ex(pid: int | str, base: int | str, offsets: list[int | str]) -> dict[str, Any] | None:
    """Dereferences a deep pointer in a remote process."""
    address = libmem.deep_pointer_ex(
        _resolve_process(pid),
        _as_non_negative_int(base, "base"),
        _as_int_list(offsets, "offsets"),
    )
    return _serialize_address(address)


@mcp.tool()
def data_scan(data: str, address: int | str, scansize: int | str, encoding: str = "hex") -> dict[str, Any] | None:
    """Searches for byte data in the MCP server process. data encoding is hex, base64, or utf-8."""
    result = libmem.data_scan(
        _decode_bytes(data, encoding),
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def data_scan_ex(
    pid: int | str,
    data: str,
    address: int | str,
    scansize: int | str,
    encoding: str = "hex",
) -> dict[str, Any] | None:
    """Searches for byte data in a remote process. data encoding is hex, base64, or utf-8."""
    result = libmem.data_scan_ex(
        _resolve_process(pid),
        _decode_bytes(data, encoding),
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def pattern_scan(
    pattern: str,
    mask: str,
    address: int | str,
    scansize: int | str,
    encoding: str = "hex",
) -> dict[str, Any] | None:
    """Searches for a byte pattern with a mask in the MCP server process. pattern encoding is hex, base64, or utf-8."""
    result = libmem.pattern_scan(
        _decode_bytes(pattern, encoding),
        mask,
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def pattern_scan_ex(
    pid: int | str,
    pattern: str,
    mask: str,
    address: int | str,
    scansize: int | str,
    encoding: str = "hex",
) -> dict[str, Any] | None:
    """Searches for a byte pattern with a mask in a remote process. pattern encoding is hex, base64, or utf-8."""
    result = libmem.pattern_scan_ex(
        _resolve_process(pid),
        _decode_bytes(pattern, encoding),
        mask,
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def sig_scan(signature: str, address: int | str, scansize: int | str) -> dict[str, Any] | None:
    """Searches for a byte signature in the MCP server process."""
    result = libmem.sig_scan(
        signature,
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def sig_scan_ex(pid: int | str, signature: str, address: int | str, scansize: int | str) -> dict[str, Any] | None:
    """Searches for a byte signature in a remote process."""
    result = libmem.sig_scan_ex(
        _resolve_process(pid),
        signature,
        _as_non_negative_int(address, "address"),
        _as_non_negative_int(scansize, "scansize"),
    )
    return _serialize_address(result)


@mcp.tool()
def get_architecture() -> dict[str, Any]:
    """Gets the current processor architecture."""
    architecture = libmem.get_architecture()
    return {
        "architecture": str(architecture),
        "supported_architectures": sorted(name for name in dir(libmem) if name.startswith("ARCH_")),
    }


@mcp.tool()
def assemble(code: str) -> dict[str, Any] | None:
    """Assembles one instruction from text for the current architecture."""
    return _serialize_instruction(libmem.assemble(code))


@mcp.tool()
def assemble_ex(code: str, arch: str, runtime_address: int | str = 0) -> dict[str, Any] | None:
    """Assembles instructions from text for an architecture and runtime address. arch examples: x64, ARCH_X64, LM_ARCH_X64."""
    data = libmem.assemble_ex(code, _resolve_arch(arch), _as_non_negative_int(runtime_address, "runtime_address"))
    if data is None:
        return None
    return _serialize_bytes(data)


@mcp.tool()
def disassemble(machine_code: int | str) -> dict[str, Any] | None:
    """Disassembles one instruction from an address in the MCP server process."""
    return _serialize_instruction(libmem.disassemble(_as_non_negative_int(machine_code, "machine_code")))


@mcp.tool()
def disassemble_ex(
    machine_code: int | str,
    arch: str,
    max_size: int | str,
    instructions_count: int | str,
    runtime_address: int | str = 0,
) -> list[dict[str, Any]] | None:
    """Disassembles instructions from an address in the MCP server process."""
    instructions = libmem.disassemble_ex(
        _as_non_negative_int(machine_code, "machine_code"),
        _resolve_arch(arch),
        _as_non_negative_int(max_size, "max_size"),
        _as_non_negative_int(instructions_count, "instructions_count"),
        _as_non_negative_int(runtime_address, "runtime_address"),
    )
    if instructions is None:
        return None
    return [cast(dict[str, Any], _serialize_instruction(instruction)) for instruction in instructions if instruction is not None]


@mcp.tool()
def code_length(machine_code: int | str, min_length: int | str) -> int | None:
    """Gets the minimum instruction-aligned length for code in the MCP server process."""
    return libmem.code_length(
        _as_non_negative_int(machine_code, "machine_code"),
        _as_non_negative_int(min_length, "min_length"),
    )


@mcp.tool()
def code_length_ex(pid: int | str, machine_code: int | str, min_length: int | str) -> int | None:
    """Gets the minimum instruction-aligned length for code in a remote process."""
    return libmem.code_length_ex(
        _resolve_process(pid),
        _as_non_negative_int(machine_code, "machine_code"),
        _as_non_negative_int(min_length, "min_length"),
    )


# ── mutating libmem tools ─────────────────────────────────────────────────────
# Defined unconditionally but only registered as MCP tools when WRITES_ENABLED
# (LIBMEM_MCP_ENABLE_WRITES) is set. Every function below mutates the target
# process: writes, allocation, hooks, protection changes, or module loading.


def _as_byte_value(value: int | str, name: str) -> int:
    number = _as_int(value, name)
    if not 0 <= number <= 255:
        raise ValueError(f"{name} must be a single byte value between 0 and 255")
    return number


def write_memory(dest: int | str, source: str, encoding: str = "hex") -> dict[str, Any]:
    """Writes bytes into the MCP server process. source encoding is hex, base64, or utf-8."""
    address = _as_non_negative_int(dest, "dest")
    payload = _decode_bytes(source, encoding)
    success = bool(libmem.write_memory(address, payload))
    return {"success": success, "bytes_written": len(payload), "dest": address, "dest_hex": _hex(address)}


def write_memory_ex(pid: int | str, dest: int | str, source: str, encoding: str = "hex") -> dict[str, Any]:
    """Writes bytes into a remote process. source encoding is hex, base64, or utf-8."""
    address = _as_non_negative_int(dest, "dest")
    payload = _decode_bytes(source, encoding)
    success = bool(libmem.write_memory_ex(_resolve_process(pid), address, payload))
    return {"success": success, "bytes_written": len(payload), "dest": address, "dest_hex": _hex(address)}


def set_memory(dest: int | str, byte: int | str, size: int | str) -> dict[str, Any]:
    """Fills memory in the MCP server process with a single byte value (0-255)."""
    address = _as_non_negative_int(dest, "dest")
    fill = _as_byte_value(byte, "byte")
    length = _as_non_negative_int(size, "size")
    success = bool(libmem.set_memory(address, bytes([fill]), length))
    return {"success": success, "dest": address, "dest_hex": _hex(address), "byte": fill, "size": length}


def set_memory_ex(pid: int | str, dest: int | str, byte: int | str, size: int | str) -> dict[str, Any]:
    """Fills memory in a remote process with a single byte value (0-255)."""
    address = _as_non_negative_int(dest, "dest")
    fill = _as_byte_value(byte, "byte")
    length = _as_non_negative_int(size, "size")
    success = bool(libmem.set_memory_ex(_resolve_process(pid), address, bytes([fill]), length))
    return {"success": success, "dest": address, "dest_hex": _hex(address), "byte": fill, "size": length}


def alloc_memory(size: int | str, prot: str) -> dict[str, Any] | None:
    """Allocates memory in the MCP server process. prot is an rwx combo such as 'rw' or 'rwx'."""
    address = libmem.alloc_memory(_as_non_negative_int(size, "size"), _resolve_prot(prot))
    result = _serialize_address(address)
    if result is not None:
        result["protection"] = str(_resolve_prot(prot))
        result["size"] = _as_non_negative_int(size, "size")
    return result


def alloc_memory_ex(pid: int | str, size: int | str, prot: str) -> dict[str, Any] | None:
    """Allocates memory in a remote process. prot is an rwx combo such as 'rw' or 'rwx'."""
    address = libmem.alloc_memory_ex(_resolve_process(pid), _as_non_negative_int(size, "size"), _resolve_prot(prot))
    result = _serialize_address(address)
    if result is not None:
        result["protection"] = str(_resolve_prot(prot))
        result["size"] = _as_non_negative_int(size, "size")
    return result


def free_memory(address: int | str, size: int | str) -> dict[str, Any]:
    """Frees memory previously allocated in the MCP server process."""
    target = _as_non_negative_int(address, "address")
    length = _as_non_negative_int(size, "size")
    return {"success": bool(libmem.free_memory(target, length)), "address": target, "address_hex": _hex(target), "size": length}


def free_memory_ex(pid: int | str, address: int | str, size: int | str) -> dict[str, Any]:
    """Frees memory previously allocated in a remote process."""
    target = _as_non_negative_int(address, "address")
    length = _as_non_negative_int(size, "size")
    success = bool(libmem.free_memory_ex(_resolve_process(pid), target, length))
    return {"success": success, "address": target, "address_hex": _hex(target), "size": length}


def prot_memory(address: int | str, size: int | str, prot: str) -> dict[str, Any]:
    """Changes memory protection in the MCP server process and returns the previous protection."""
    target = _as_non_negative_int(address, "address")
    length = _as_non_negative_int(size, "size")
    requested = _resolve_prot(prot)
    previous = libmem.prot_memory(target, length, requested)
    return {
        "success": previous is not None,
        "address": target,
        "address_hex": _hex(target),
        "size": length,
        "requested_protection": str(requested),
        "previous_protection": _serialize_prot(previous),
    }


def prot_memory_ex(pid: int | str, address: int | str, size: int | str, prot: str) -> dict[str, Any]:
    """Changes memory protection in a remote process and returns the previous protection."""
    target = _as_non_negative_int(address, "address")
    length = _as_non_negative_int(size, "size")
    requested = _resolve_prot(prot)
    previous = libmem.prot_memory_ex(_resolve_process(pid), target, length, requested)
    return {
        "success": previous is not None,
        "address": target,
        "address_hex": _hex(target),
        "size": length,
        "requested_protection": str(requested),
        "previous_protection": _serialize_prot(previous),
    }


def _serialize_trampoline(trampoline: Any) -> dict[str, Any] | None:
    if trampoline is None:
        return None
    address, size = trampoline
    return {
        "hooked": True,
        "trampoline_address": address,
        "trampoline_address_hex": _hex(address),
        "trampoline_size": size,
        "unhook_with": "Pass from_address, trampoline_address, and trampoline_size to unhook_code.",
    }


def hook_code(from_address: int | str, to_address: int | str) -> dict[str, Any] | None:
    """Hooks/detours code in the MCP server process, returning the trampoline used to call the original."""
    trampoline = libmem.hook_code(
        _as_non_negative_int(from_address, "from_address"),
        _as_non_negative_int(to_address, "to_address"),
    )
    return _serialize_trampoline(trampoline)


def hook_code_ex(pid: int | str, from_address: int | str, to_address: int | str) -> dict[str, Any] | None:
    """Hooks/detours code in a remote process, returning the trampoline used to call the original."""
    trampoline = libmem.hook_code_ex(
        _resolve_process(pid),
        _as_non_negative_int(from_address, "from_address"),
        _as_non_negative_int(to_address, "to_address"),
    )
    return _serialize_trampoline(trampoline)


def unhook_code(from_address: int | str, trampoline_address: int | str, trampoline_size: int | str) -> dict[str, Any]:
    """Removes a code hook in the MCP server process using the trampoline returned by hook_code."""
    origin = _as_non_negative_int(from_address, "from_address")
    trampoline = (_as_non_negative_int(trampoline_address, "trampoline_address"), _as_non_negative_int(trampoline_size, "trampoline_size"))
    return {"success": bool(libmem.unhook_code(origin, trampoline)), "from_address": origin, "from_address_hex": _hex(origin)}


def unhook_code_ex(pid: int | str, from_address: int | str, trampoline_address: int | str, trampoline_size: int | str) -> dict[str, Any]:
    """Removes a code hook in a remote process using the trampoline returned by hook_code_ex."""
    origin = _as_non_negative_int(from_address, "from_address")
    trampoline = (_as_non_negative_int(trampoline_address, "trampoline_address"), _as_non_negative_int(trampoline_size, "trampoline_size"))
    success = bool(libmem.unhook_code_ex(_resolve_process(pid), origin, trampoline))
    return {"success": success, "from_address": origin, "from_address_hex": _hex(origin)}


def load_module(module_path: str) -> dict[str, Any] | None:
    """Loads a module (shared library) into the MCP server process."""
    return _serialize_module(libmem.load_module(module_path))


def load_module_ex(pid: int | str, module_path: str) -> dict[str, Any] | None:
    """Loads a module (shared library) into a remote process."""
    return _serialize_module(libmem.load_module_ex(_resolve_process(pid), module_path))


def unload_module(
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
) -> dict[str, Any]:
    """Unloads a module from the MCP server process. Identify it by name, base, or path."""
    module = _resolve_module(module_name, module_base, module_path)
    return {"success": bool(libmem.unload_module(module)), "module": _serialize_module(module)}


def unload_module_ex(
    pid: int | str,
    module_name: str | None = None,
    module_base: int | str | None = None,
    module_path: str | None = None,
) -> dict[str, Any]:
    """Unloads a module from a remote process. Identify it by name, base, or path."""
    module = _resolve_module(module_name, module_base, module_path, pid)
    return {"success": bool(libmem.unload_module_ex(_resolve_process(pid), module)), "module": _serialize_module(module)}


# ── Vmt (virtual method table) hooking ────────────────────────────────────────
# Vmt instances are stateful (they hold the original function pointers), so they
# are kept in an in-process registry and addressed by an integer handle.
_vmt_registry: dict[int, Any] = {}
_vmt_ids = itertools.count(1)


def _resolve_vmt(handle: int | str) -> Any:
    handle_id = _as_non_negative_int(handle, "handle")
    vmt = _vmt_registry.get(handle_id)
    if vmt is None:
        raise ValueError(f"No Vmt with handle {handle_id}. Create one with vmt_create first.")
    return vmt


def vmt_create(vtable_address: int | str) -> dict[str, Any]:
    """Creates a Vmt manager for a virtual method table at the given address and returns its handle."""
    address = _as_non_negative_int(vtable_address, "vtable_address")
    handle = next(_vmt_ids)
    _vmt_registry[handle] = libmem.Vmt(address)
    return {"handle": handle, "vtable_address": address, "vtable_address_hex": _hex(address)}


def vmt_list() -> list[dict[str, Any]]:
    """Lists the currently held Vmt handles."""
    return [{"handle": handle} for handle in sorted(_vmt_registry)]


def vmt_hook(handle: int | str, index: int | str, dst: int | str) -> dict[str, Any]:
    """Hooks the VMT function at an index, redirecting it to dst. Use vmt_get_original to call the original."""
    vmt = _resolve_vmt(handle)
    function_index = _as_non_negative_int(index, "index")
    destination = _as_non_negative_int(dst, "dst")
    vmt.hook(function_index, destination)
    return {"success": True, "handle": _as_non_negative_int(handle, "handle"), "index": function_index, "dst": destination, "dst_hex": _hex(destination)}


def vmt_unhook(handle: int | str, index: int | str) -> dict[str, Any]:
    """Unhooks the VMT function at an index, restoring the original entry."""
    vmt = _resolve_vmt(handle)
    function_index = _as_non_negative_int(index, "index")
    vmt.unhook(function_index)
    return {"success": True, "handle": _as_non_negative_int(handle, "handle"), "index": function_index}


def vmt_get_original(handle: int | str, index: int | str) -> dict[str, Any] | None:
    """Gets the original (pre-hook) VMT function address at an index."""
    vmt = _resolve_vmt(handle)
    return _serialize_address(vmt.get_original(_as_non_negative_int(index, "index")))


def vmt_reset(handle: int | str) -> dict[str, Any]:
    """Resets the VMT, restoring all original function entries."""
    vmt = _resolve_vmt(handle)
    vmt.reset()
    return {"success": True, "handle": _as_non_negative_int(handle, "handle")}


def vmt_destroy(handle: int | str) -> dict[str, Any]:
    """Resets and releases a Vmt handle. Restores all entries before dropping it."""
    handle_id = _as_non_negative_int(handle, "handle")
    vmt = _resolve_vmt(handle_id)
    vmt.reset()
    del _vmt_registry[handle_id]
    return {"success": True, "handle": handle_id, "remaining_handles": sorted(_vmt_registry)}


_MUTATING_TOOLS = [
    write_memory,
    write_memory_ex,
    set_memory,
    set_memory_ex,
    alloc_memory,
    alloc_memory_ex,
    free_memory,
    free_memory_ex,
    prot_memory,
    prot_memory_ex,
    hook_code,
    hook_code_ex,
    unhook_code,
    unhook_code_ex,
    load_module,
    load_module_ex,
    unload_module,
    unload_module_ex,
    vmt_create,
    vmt_list,
    vmt_hook,
    vmt_unhook,
    vmt_get_original,
    vmt_reset,
    vmt_destroy,
]

if WRITES_ENABLED:
    for _tool_fn in _MUTATING_TOOLS:
        mcp.tool()(_tool_fn)
    _logger.warning(
        "LIBMEM_MCP_ENABLE_WRITES is set — %d mutating libmem tools are EXPOSED (memory writes, hooks, alloc, etc.)",
        len(_MUTATING_TOOLS),
    )
else:
    _logger.info(
        "Mutating libmem tools are gated off; set LIBMEM_MCP_ENABLE_WRITES=1 to expose %d additional tools",
        len(_MUTATING_TOOLS),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="libmem-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport to use. 'streamable-http' starts an HTTP server you connect to; 'stdio' is for clients that spawn the process.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FASTMCP_PORT", "8765")),
        help="Port for streamable-http transport (default: 8765)",
    )
    ns = parser.parse_args()

    if ns.transport == "streamable-http":
        mcp.settings.port = ns.port

    # Intercept at the ToolManager.call_tool level — the single async choke
    # point for every MCP tool call, regardless of how FastMCP routes internally.
    import asyncio

    _original_call_tool = mcp._tool_manager.call_tool

    async def _logged_call_tool(name: str, arguments: dict, *args: Any, **kwargs: Any) -> Any:
        arg_str = ", ".join(f"{k}={v!r}" for k, v in (arguments or {}).items())
        _logger.trace(">> %s(%s)", name, arg_str)
        t0 = time.monotonic()
        try:
            result = await _original_call_tool(name, arguments, *args, **kwargs)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            _logger.error("!! %s (%.1f ms) raised %s: %s", name, elapsed, type(exc).__name__, exc)
            raise
        elapsed = (time.monotonic() - t0) * 1000
        try:
            summary = json.dumps(result, default=str)
        except Exception:
            summary = repr(result)
        _logger.debug("<< %s  (%.1f ms)  %s", name, elapsed, summary)
        return result

    mcp._tool_manager.call_tool = _logged_call_tool  # type: ignore[method-assign]
    _logger.info("libmem-mcp transport=%s port=%s", ns.transport, ns.port if ns.transport == "streamable-http" else "n/a")
    try:
        mcp.run(transport=ns.transport)
    finally:
        _mlog.stop()
