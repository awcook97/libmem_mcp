# libmem-mcp

An MCP server exposing [libmem](https://github.com/rdbo/libmem) APIs for process/memory inspection. Read-only by default; mutating APIs are gated behind an environment variable.

---

## Prerequisites

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager (used for everything)
- **Python 3.14+** — uv will manage this for you
- **[libmem](https://github.com/rdbo/libmem)** — the native library itself; follow the build/install instructions in that repo. The Python package wraps it but does not bundle the native `.so`/`.dll`.

---

## Installation

```bash
git clone https://github.com/awcook97/libmem_mcp.git
cd libmem_mcp
uv sync
```

---

## MCP Client Setup

Replace `/absolute/path/to/libmem_mcp` with where you cloned the repo.

### VS Code (GitHub Copilot)

Create `.vscode/mcp.json` in your workspace (a template is at `.vscode/mcp.json.example`):

```json
{
  "servers": {
    "libmem-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/libmem_mcp/.venv/bin/python",
      "args": ["-m", "libmem_mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/libmem_mcp/src"
      }
    }
  }
}
```

VS Code will spawn the MCP server automatically when you open the workspace.

### Claude Desktop

Config file locations:
- **Linux/macOS:** `~/.config/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "libmem-mcp": {
      "command": "/absolute/path/to/libmem_mcp/.venv/bin/python",
      "args": ["-m", "libmem_mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/libmem_mcp/src"
      }
    }
  }
}
```

---

## What it can do

Always exposed (read-only):

| Category | Functions exposed |
|---|---|
| Processes | `find_process`, `get_process`, `get_process_ex`, `enum_processes`, `is_process_alive`, `get_command_line` |
| Threads | `enum_threads`, `enum_threads_ex`, `get_thread`, `get_thread_ex`, `get_thread_process` |
| Modules | `find_module`, `find_module_ex`, `enum_modules`, `enum_modules_ex` |
| Symbols | `enum_symbols`, `enum_symbols_demangled`, `find_symbol_address`, `find_symbol_address_demangled`, `demangle_symbol` |
| Segments | `find_segment`, `find_segment_ex`, `enum_segments`, `enum_segments_ex` |
| Memory | `read_memory`, `read_memory_ex`, `pattern_scan`, `sig_scan`, `data_scan`, `deep_pointer` (+ `_ex` variants) |
| Code | `disassemble`, `assemble`, `code_length` (+ `_ex` variants), `get_architecture`, `get_bits`, `get_system_bits` |

Call `libmem_mcp_info` to see exactly which tools are active in the current session and the accepted address/byte/protection input formats.

Memory reads return both hex and base64.

## Mutating tools (off by default)

Memory writes, `set_memory`, alloc/free, protection changes, code hooks, module load/unload, and VMT hooks are **only registered when `LIBMEM_MCP_ENABLE_WRITES` is set**. Leave it unset and the server is a read-only inspector — the tools simply don't exist in the session.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LIBMEM_MCP_MAX_READ_BYTES` | `1048576` (1 MiB) | Max bytes per `read_memory` call |
| `LIBMEM_MCP_ENABLE_WRITES` | unset | Set to `1`/`true` to register the mutating libmem tools |
| `LIBMEM_MCP_LOG_DIR` | `output/` in the repo | Where the autologger writes its log files |

## Logging

Every tool call is logged (name, arguments, timing, summarized result) to a file under `LIBMEM_MCP_LOG_DIR`, so you can always see what your idiot is doing.
