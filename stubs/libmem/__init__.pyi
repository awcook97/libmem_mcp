"""Type stub for the libmem package (libmem 5.1.4).

Mirrors libmem/__init__.py: friendly aliases for the C record types, the
PROT_*/ARCH_* constants, and the snake_case wrapper functions. The underlying
definitions live in the _libmem stub.
"""

from libmem._libmem import (
    lm_arch_t as Arch,
    lm_inst_t as Inst,
    lm_module_t as Module,
    lm_process_t as Process,
    lm_prot_t as Prot,
    lm_segment_t as Segment,
    lm_symbol_t as Symbol,
    lm_thread_t as Thread,
    lm_vmt_t as Vmt,
)
from libmem._libmem import (
    LM_PROT_R as PROT_R,
    LM_PROT_W as PROT_W,
    LM_PROT_X as PROT_X,
    LM_PROT_XR as PROT_XR,
    LM_PROT_XW as PROT_XW,
    LM_PROT_RW as PROT_RW,
    LM_PROT_XRW as PROT_XRW,
    LM_ARCH_ARMV7 as ARCH_ARMV7,
    LM_ARCH_ARMV8 as ARCH_ARMV8,
    LM_ARCH_THUMBV7 as ARCH_THUMBV7,
    LM_ARCH_THUMBV8 as ARCH_THUMBV8,
    LM_ARCH_ARMV7EB as ARCH_ARMV7EB,
    LM_ARCH_THUMBV7EB as ARCH_THUMBV7EB,
    LM_ARCH_ARMV8EB as ARCH_ARMV8EB,
    LM_ARCH_THUMBV8EB as ARCH_THUMBV8EB,
    LM_ARCH_AARCH64 as ARCH_AARCH64,
    LM_ARCH_MIPS as ARCH_MIPS,
    LM_ARCH_MIPS64 as ARCH_MIPS64,
    LM_ARCH_MIPSEL as ARCH_MIPSEL,
    LM_ARCH_MIPSEL64 as ARCH_MIPSEL64,
    LM_ARCH_X86_16 as ARCH_X86_16,
    LM_ARCH_X86 as ARCH_X86,
    LM_ARCH_X64 as ARCH_X64,
    LM_ARCH_PPC32 as ARCH_PPC32,
    LM_ARCH_PPC64 as ARCH_PPC64,
    LM_ARCH_PPC64LE as ARCH_PPC64LE,
    LM_ARCH_SPARC as ARCH_SPARC,
    LM_ARCH_SPARC64 as ARCH_SPARC64,
    LM_ARCH_SPARCEL as ARCH_SPARCEL,
    LM_ARCH_SYSZ as ARCH_SYSZ,
    LM_ARCH_MAX as ARCH_MAX,
)

# Aliases imported under a different name are only re-exported (accessible as
# libmem.Vmt, libmem.PROT_XRW, ...) if they appear here.
__all__ = [
    "Arch", "Inst", "Module", "Process", "Prot", "Segment", "Symbol", "Thread", "Vmt",
    "PROT_R", "PROT_W", "PROT_X", "PROT_XR", "PROT_XW", "PROT_RW", "PROT_XRW",
    "ARCH_ARMV7", "ARCH_ARMV8", "ARCH_THUMBV7", "ARCH_THUMBV8",
    "ARCH_ARMV7EB", "ARCH_THUMBV7EB", "ARCH_ARMV8EB", "ARCH_THUMBV8EB",
    "ARCH_AARCH64", "ARCH_MIPS", "ARCH_MIPS64", "ARCH_MIPSEL", "ARCH_MIPSEL64",
    "ARCH_X86_16", "ARCH_X86", "ARCH_X64", "ARCH_PPC32", "ARCH_PPC64", "ARCH_PPC64LE",
    "ARCH_SPARC", "ARCH_SPARC64", "ARCH_SPARCEL", "ARCH_SYSZ", "ARCH_MAX",
    "enum_processes", "get_process", "get_process_ex", "get_command_line",
    "find_process", "is_process_alive", "get_bits", "get_system_bits",
    "enum_threads", "enum_threads_ex", "get_thread", "get_thread_ex", "get_thread_process",
    "enum_modules", "enum_modules_ex", "find_module", "find_module_ex",
    "load_module", "load_module_ex", "unload_module", "unload_module_ex",
    "enum_symbols", "find_symbol_address", "demangle_symbol",
    "enum_symbols_demangled", "find_symbol_address_demangled",
    "enum_segments", "enum_segments_ex", "find_segment", "find_segment_ex",
    "read_memory", "read_memory_ex", "write_memory", "write_memory_ex",
    "set_memory", "set_memory_ex", "prot_memory", "prot_memory_ex",
    "alloc_memory", "alloc_memory_ex", "free_memory", "free_memory_ex",
    "deep_pointer", "deep_pointer_ex", "data_scan", "data_scan_ex",
    "pattern_scan", "pattern_scan_ex", "sig_scan", "sig_scan_ex",
    "hook_code", "hook_code_ex", "unhook_code", "unhook_code_ex",
    "get_architecture", "assemble", "assemble_ex", "disassemble", "disassemble_ex",
    "code_length", "code_length_ex",
]

def enum_processes() -> list[Process] | None:
    """Lists all current living processes"""
def get_process() -> Process | None:
    """Gets information about the calling process"""
def get_process_ex(pid: int) -> Process | None:
    """Gets information about a process from a process ID"""
def get_command_line(proc: Process) -> list[str] | None:
    """Retrieves the command line arguments of a process"""
def find_process(process_name: str) -> Process | None:
    """Searches for an existing process"""
def is_process_alive(process: Process) -> bool:
    """Checks if a process is alive"""
def get_bits() -> int:
    """Checks if a process is alive"""
def get_system_bits() -> int:
    """Checks if a process is alive"""
def enum_threads() -> list[Thread] | None:
    """Lists all threads from the calling process"""
def enum_threads_ex(process: Process) -> list[Thread] | None:
    """Lists all threads from the calling process"""
def get_thread() -> Thread | None:
    """Get information about the calling thread"""
def get_thread_ex(process: Process) -> Thread | None:
    """Get information about a remote thread"""
def get_thread_process(thread: Thread) -> Process | None:
    """Gets information about a process from a thread"""
def enum_modules() -> list[Module] | None:
    """Lists all modules from the calling process"""
def enum_modules_ex(process: Process) -> list[Module] | None:
    """Lists all modules from a remote process"""
def find_module(module_name: str) -> Module | None:
    """Searches for a module in the current process"""
def find_module_ex(process: Process, module_name: str) -> Module | None:
    """Searches for a module in a remote process"""
def load_module(module_path: str) -> Module | None:
    """Loads a module into the current process"""
def load_module_ex(process: Process, module_path: str) -> Module | None:
    """Loads a module into a remote process"""
def unload_module(module: Module) -> bool:
    """Unloads a module from the current process"""
def unload_module_ex(process: Process, module: Module) -> bool:
    """Unloads a module from a remote process"""
def enum_symbols(module: Module) -> list[Symbol] | None:
    """Lists all symbols from a module"""
def find_symbol_address(module: Module, symbol_name: str) -> int | None:
    """Searches for a symbol in a module"""
def demangle_symbol(mangled_symbol: str) -> str | None:
    """Demangles a mangled symbol from a module"""
def enum_symbols_demangled(module: Module) -> list[Symbol] | None:
    """Lists all demangled symbols from a module"""
def find_symbol_address_demangled(module: Module, demangled_symbol_name: str) -> int | None:
    """Searches for a demangled symbol in a module"""
def enum_segments() -> list[Segment] | None:
    """Lists all segments from the calling process"""
def enum_segments_ex(process: Process) -> list[Segment] | None:
    """Lists all segments from a remote process"""
def find_segment(address: int) -> Segment | None:
    """Get information about the segment of an address in the current process"""
def find_segment_ex(process: Process, address: int) -> Segment | None:
    """Get information about the segment of an address in a remote process"""
def read_memory(src: int, size: int) -> bytearray | None:
    """Read memory from the calling process"""
def read_memory_ex(process: Process, source: int, size: int) -> bytearray | None:
    """Read memory from a remote process"""
def write_memory(dest: int, source: bytearray) -> bool:
    """Write memory to the calling process"""
def write_memory_ex(process: Process, dest: int, source: bytearray) -> bool:
    """Write memory to a remote process"""
def set_memory(dest: int, byte: bytes, size: int) -> bool:
    """Set memory to a byte in the current process"""
def set_memory_ex(process: Process, dest: int, byte: bytes, size: int) -> bool:
    """Set memory to a byte in a remote process"""
def prot_memory(address: int, size: int, prot: Prot) -> Prot | None:
    """Change memory protection flags of a region in the current process"""
def prot_memory_ex(process: Process, address: int, size: int, prot: Prot) -> Prot | None:
    """Change memory protection flags of a region in a remote process"""
def alloc_memory(size: int, prot: Prot) -> int | None:
    """Allocate memory in the current process"""
def alloc_memory_ex(process: Process, size: int, prot: Prot) -> int | None:
    """Allocate memory in a remote process"""
def free_memory(address: int, size: int) -> bool:
    """Free memory in the current process"""
def free_memory_ex(process: Process, address: int, size: int) -> bool:
    """Free memory in a remote process"""
def deep_pointer(base: int, offsets: list[int]) -> int | None:
    """Dereference a deep pointer in the current process, usually result of a pointer map or pointer scan"""
def deep_pointer_ex(process: Process, base: int, offsets: list[int]) -> int | None:
    """Dereference a deep pointer in a remote process, usually result of a pointer map or pointer scan"""
def data_scan(data: bytearray, address: int, scansize: int) -> int | None:
    """Search for a byte array in the current process"""
def data_scan_ex(process: Process, data: bytearray, address: int, scansize: int) -> int | None:
    """Search for a byte array in a remote process"""
def pattern_scan(pattern: bytearray, mask: str, address: int, scansize: int) -> int | None:
    """Search for a byte pattern with a mask filter in the current process"""
def pattern_scan_ex(process: Process, pattern: bytearray, mask: str, address: int, scansize: int) -> int | None:
    """Search for a byte pattern with a mask filter in a remote process"""
def sig_scan(signature: str, address: int, scansize: int) -> int | None:
    """Search for a byte signature that can contain filters in the current process"""
def sig_scan_ex(process: Process, signature: str, address: int, scansize: int) -> int | None:
    """Search for a byte signature that can contain filters in a remote process"""
def hook_code(from_address: int, to_address: int) -> tuple[int, int] | None:
    """Hook/detour code in the current process, returning a gateway/trampoline"""
def hook_code_ex(process: Process, from_address: int, to_address: int) -> tuple[int, int] | None:
    """Hook/detour code in a remote process, returning a gateway/trampoline"""
def unhook_code(from_address: int, trampoline: tuple[int, int]) -> bool:
    """Unhook/restore code in the current process"""
def unhook_code_ex(process: Process, from_address: int, trampoline: tuple[int, int]) -> bool:
    """Unhook/restore code in a remote process"""
def get_architecture() -> Arch:
    """Gets the current processor architecture"""
def assemble(code: str) -> Inst | None:
    """Assemble instruction from text"""
def assemble_ex(code: str, arch: Arch, runtime_address: int) -> bytearray | None:
    """Assemble instructions from text"""
def disassemble(machine_code: int) -> Inst | None:
    """Disassemble instruction from an address in the current process"""
def disassemble_ex(machine_code: int, arch: Arch, max_size: int, instructions_count: int, runtime_address: int) -> list[Inst] | None:
    """Disassemble instructions from an address in the current process"""
def code_length(machine_code: int, min_length: int) -> int | None:
    """Get the minimum instruction aligned length for a code region in the current process"""
def code_length_ex(process: Process, machine_code: int, min_length: int) -> int | None:
    """Get the minimum instruction aligned length for a code region in a remote process"""
