# libmem-mcp + gameinput-mcp

Two independent MCP servers in one repo, sharing a common library.

- **libmem-mcp** — read-only process/memory inspector via [libmem](https://github.com/rdbo/libmem)
- **gameinput-mcp** — sends keyboard/mouse input to games, but **only the keys you declare in a config file you own**

---

## Prerequisites

### Required for both servers

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager (used for everything)
- **Python 3.14+** — uv will manage this for you

### Required for `libmem-mcp`

- **[libmem](https://github.com/rdbo/libmem)** — the native library itself; follow the build/install instructions in that repo. The Python package wraps it but does not bundle the native `.so`/`.dll`.

### Required for `gameinput-mcp` on Linux

```bash
sudo apt install xdotool        # Debian/Ubuntu
sudo pacman -S xdotool          # Arch
```

---

## Installation

```bash
git clone https://github.com/awcook97/libmem_mcp.git
cd libmem_mcp
uv sync
```

**Optional extras** (pick what you need):

```bash
# Better screenshot cropping on Linux/X11 (python-xlib)
uv sync --extra gameinput-x11

# Windows input backend (pywin32)
uv sync --extra gameinput-win32
```

---

## Architecture

There are three processes, not two:

| Process | Who starts it | Purpose |
|---|---|---|
| `libmem-mcp` | VS Code (stdio) | MCP server for memory inspection |
| `gameinput-mcp` | VS Code (stdio) | Thin MCP bridge — forwards tool calls to daemon |
| `gameinput-daemon` | **You** (your terminal) | All actual input/screenshot logic. Kill switch. |

VS Code spawns the MCP servers automatically. You run only the daemon.

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
    },
    "gameinput-mcp": {
      "type": "stdio",
      "command": "/absolute/path/to/libmem_mcp/.venv/bin/python",
      "args": ["-m", "gameinput_mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/libmem_mcp/src"
      }
    }
  }
}
```

VS Code will spawn both MCP servers automatically when you open the workspace.

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
    },
    "gameinput-mcp": {
      "command": "/absolute/path/to/libmem_mcp/.venv/bin/python",
      "args": ["-m", "gameinput_mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/libmem_mcp/src"
      }
    }
  }
}
```

---

## Running the daemon

Before the AI can send any input, you need `gameinput-daemon` running in your terminal. This is the kill switch — **Ctrl+C there and the AI can't touch anything.**

```bash
./start.sh --config path/to/gameinput.config.json

# or directly:
uv run gameinput-daemon --config path/to/gameinput.config.json

# optional flags:
#   --port N          listen port (default: 8767)
#   --host ADDR       bind address (default: 127.0.0.1)
#   --log-level LEVEL trace/debug/info/warn/error (default: debug)
```

`libmem-mcp` has no daemon — VS Code spawns it directly, no extra step needed.

---

## libmem-mcp

A read-only MCP server that exposes [libmem](https://github.com/rdbo/libmem) APIs for process/memory inspection.

### What it can do

| Category | Functions exposed |
|---|---|
| Processes | `find_process`, `get_process`, `enum_processes`, `is_process_alive` |
| Threads | `enum_threads`, `get_thread` |
| Modules | `find_module`, `enum_modules`, `enum_symbols` |
| Segments | `find_segment`, `enum_segments` |
| Memory | `read_memory`, `pattern_scan`, `sig_scan`, `data_scan`, `deep_pointer` |
| Code | `disassemble`, `assemble`, `code_length` |

### What it cannot do

Hooks, allocation, memory writes, set protection, free memory, module load/unload — none of these are exposed. It's a read-only inspector.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `LIBMEM_MCP_MAX_READ_BYTES` | `1048576` (1 MiB) | Max bytes per `read_memory` call |
| `LIBMEM_MCP_LOG_LEVEL` | `info` | Log level (`trace`, `debug`, `info`, `warning`, `error`) |

Memory reads return both hex and base64.

---

## gameinput-mcp

Sends keyboard and mouse input to user-declared target processes. The AI can only use keys and macros **you declare in a config file you own and write**. The server never modifies the config.

### The allowlist guarantee

There is no `press_key`, `type_text`, or `mouse_at` tool. Every input goes through a gated backend that checks each key against your declared allowlist before it reaches the OS. If a key isn't in your keymap, it raises `DisallowedKeyError` and nothing is sent.

### Kill switch

**You run `gameinput-daemon` in your own terminal. Ctrl+C kills it.** The AI gets no response on any gameinput tool call while the daemon is down. The MCP bridge (`gameinput-mcp`) is a tiny process with zero power on its own — the daemon has everything.

```bash
uv run gameinput-daemon --config path/to/gameinput.config.json
```

Do not background it. The terminal is the kill switch.

---

### Config file

You write this. The server only reads it.

**Resolution order:** `--config` CLI flag → `GAMEINPUT_MCP_CONFIG` env var → walk up from CWD looking for `gameinput.config.json` or `.gameinput/config.json`.

```jsonc
{
  "targets": {
    "game1": {
      "match": { "name": "game.exe", "pid": null },
      "window_title_regex": "My Game.*",
      "platform": "auto",
      "keymap": "GAME_DEFAULT",
      "macros": ["chat", "ability1"]
    }
  },
  "keymaps": {
    "GAME_DEFAULT": {
      "JUMP":    { "nrm": "Space", "alt": null },
      "FORWARD": { "nrm": "W",     "alt": "Up"  },
      "ABILITY": { "nrm": "F1",    "alt": null  }
    }
  },
  "macros": {
    "chat":     [
      { "type": "key",    "value": "Return" },
      { "type": "text",   "value": "hello"  },
      { "type": "key",    "value": "Return" }
    ],
    "ability1": [
      { "type": "action", "value": "ABILITY" }
    ]
  }
}
```

**`targets` fields:**

| Field | Description |
|---|---|
| `match.name` | Process name to search for (e.g. `game.exe`) |
| `match.pid` | Exact PID (overrides name search if set) |
| `window_title_regex` | Regex matched against window title for screenshot targeting |
| `platform` | `"x11"`, `"win32"`, or `"auto"` |
| `keymap` | Name of a keymap block defined in `keymaps` |
| `macros` | List of macro names from `macros` the AI is allowed to run |

**`keymaps`:** Each entry is `ACTION_NAME: { "nrm": "Key", "alt": "Key" }`. `null` or `"clear"` means unbound — calling it returns an error, nothing is sent.

**Macro step types:**

| Type | `value` | Description |
|---|---|---|
| `key` | `"Space"`, `"Return"`, `"F1"` … | Tap a single key |
| `text` | `"any string"` | Type a string character by character |
| `delay` | `250` (milliseconds) | Pause between steps |
| `mouse` | `{"button":"left","x":100,"y":200,"relative":true}` | Mouse click |
| `action` | `"JUMP"` | Run a keymap action by name |

---

### Bulk keymap importer

If your game exports a keymap file in the supported format, convert it to JSON in one command:

```bash
uv run gameinput-mcp import-keymap path/to/keymap.cfg
uv run gameinput-mcp import-keymap path/to/keymap.cfg --keymap-name GAME_DEFAULT
```

Supported keymap format:
```
[JUMP] Nrm:Space Alt:clear
[FORWARD] Nrm:W Alt:Up
[ABILITY] Nrm:F1 Alt:clear
```

Output goes to stdout. Copy the printed JSON block into the `"keymaps"` section of your config. The importer never touches your config file.

---

### Tools exposed to the AI

| Tool | What it does |
|---|---|
| `list_targets` | All declared targets + whether the process is currently running |
| `list_actions(target)` | Keymap entries and their key bindings |
| `list_macros(target)` | Declared macros with step-by-step previews |
| `press_action(target, action, modifier)` | Press one keymap action (`nrm` or `alt`) |
| `run_macro(target, macro)` | Execute a declared macro step by step |
| `screenshot(target)` | Capture the target window |
| `get_window_info(target)` | Window title + geometry |

Every input tool (`press_action`, `run_macro`) returns three screenshots — taken before input, at +0.3s, and at +3s — as in-memory base64 PNG. No files are written to disk.

