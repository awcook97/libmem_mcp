libmem-mcp
==========

==========

## NOTE: YOU MUST HAVE `UV` AND `libmem` INSTALLED TO USE THIS SERVER. IT IS NOT INCLUDED AS A DEPENDENCY.

Please follow the instructions to install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [libmem](https://github.com/rdbo/libmem) before using this server.

===========

## Installation

```bash
git clone https://github.com/awcook97/libmem_mcp.git
cd libmem_mcp
uv sync
```

============

## What this is

A simple read-only MCP server for the Python `libmem` package. Does not write to keep you safe from anticheat, and also it'd be really stupid to give AI write access to memory. These fools can't even understand the concept of a logger, much less low level memory manipulation.

## Run

```bash
uv run libmem-mcp
```

## Scope

The server exposes read/inspect-oriented libmem APIs for processes, threads, modules, symbols, segments, memory reads, scans, deep pointers, disassembly, and assembly helpers.

The following mutating APIs are intentionally not exposed: hooks/unhooks, allocation, memory writes, set memory, protection changes, free memory, and module load/unload.

Memory reads return hex and base64. The default maximum returned read size is 1 MiB; override it with `LIBMEM_MCP_MAX_READ_BYTES`.
