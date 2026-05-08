libmem-mcp
==========

Read-only MCP server for the Python `libmem` package.

## Run

```bash
uv run libmem-mcp
```

## Scope

The server exposes read/inspect-oriented libmem APIs for processes, threads, modules, symbols, segments, memory reads, scans, deep pointers, disassembly, and assembly helpers.

The following mutating APIs are intentionally not exposed: hooks/unhooks, allocation, memory writes, set memory, protection changes, free memory, and module load/unload.

Memory reads return hex and base64. The default maximum returned read size is 1 MiB; override it with `LIBMEM_MCP_MAX_READ_BYTES`.
