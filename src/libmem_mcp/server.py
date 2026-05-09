from __future__ import annotations

import base64
import functools
import json
import os
import pathlib
import time
from collections.abc import Iterable
from typing import Any, cast

import libmem
from mcp.server.fastmcp import FastMCP

from libmem_mcp import log as _log

# ── autologger setup ─────────────────────────────────────────────────────────
_LOG_DIR = pathlib.Path(os.getenv("LIBMEM_MCP_LOG_DIR", str(pathlib.Path(__file__).parent.parent.parent / "output")))
_log_listener = _log.setup(_LOG_DIR / "mcp_autolog.log", level="trace")
_logger = _log.get_logger("mcp")
_logger.info("libmem-mcp server started, logging to %s", _LOG_DIR / "mcp_autolog.log")


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

EXPOSED_LIBMEM_FUNCTIONS = [
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

EXCLUDED_LIBMEM_FUNCTIONS = [
    "alloc_memory",
    "alloc_memory_ex",
    "free_memory",
    "free_memory_ex",
    "hook_code",
    "hook_code_ex",
    "load_module",
    "load_module_ex",
    "prot_memory",
    "prot_memory_ex",
    "set_memory",
    "set_memory_ex",
    "unhook_code",
    "unhook_code_ex",
    "unload_module",
    "unload_module_ex",
    "write_memory",
    "write_memory_ex",
]

mcp = FastMCP(
    "libmem-mcp",
    instructions=(
        "Read-only MCP wrapper for libmem. Exposes process, thread, module, "
        "symbol, segment, memory-read, scan, pointer, disassembly, and assembly "
        "helpers. Mutating libmem APIs for hooks, allocation, setting memory, "
        "protection changes, freeing, module load/unload, and memory writes are "
        "intentionally not exposed."
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


@mcp.tool()
def libmem_mcp_info() -> dict[str, Any]:
    """List the libmem APIs exposed by this read-only MCP and the APIs intentionally excluded."""
    return {
        "exposed_functions": EXPOSED_LIBMEM_FUNCTIONS,
        "excluded_functions": EXCLUDED_LIBMEM_FUNCTIONS,
        "max_read_bytes": MAX_READ_BYTES,
        "byte_input_encodings": ["hex", "base64", "utf-8"],
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


def main() -> None:
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
    try:
        mcp.run()
    finally:
        _log_listener.stop()
