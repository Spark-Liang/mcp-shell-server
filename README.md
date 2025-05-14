[English](README.md) | [中文](README-CN.md)

# MCP Shell Server

[![codecov](https://codecov.io/gh/tumf/mcp-shell-server/branch/main/graph/badge.svg)](https://codecov.io/gh/tumf/mcp-shell-server)

A secure shell command execution server implementing the Model Context Protocol (MCP). This server allows remote execution of whitelisted shell commands with support for stdin input.

<a href="https://glama.ai/mcp/servers/rt2d4pbn22"><img width="380" height="200" src="https://glama.ai/mcp/servers/rt2d4pbn22/badge" alt="mcp-shell-server MCP server" /></a>

## Features

* **Secure Command Execution**: Only whitelisted commands can be executed
* **Standard Input Support**: Pass input to commands via stdin
* **Comprehensive Output**: Returns stdout, stderr, exit status, and execution time
* **Shell Operator Safety**: Validates commands after shell operators (; , &&, ||, |)
* **Timeout Control**: Set maximum execution time for commands
* **Background Process Management**: Run long-running commands in the background and manage them
* **Web Management Interface**: Monitor and manage background processes through a web UI
* **Multiple Server Modes**: Support for stdio (default), SSE, and streamable HTTP modes

## MCP client setting in your Claude.app

### Published version

```shell
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

```json
{
  "mcpServers": {
    "shell": {
      "command": "uvx",
      "args": [
        "mcp-shell-server"
      ],
      "env": {
        "ALLOW_COMMANDS": "ls,cat,pwd,grep,wc,touch,find"
      }
    },
  }
}
```

### Local version

#### Configuration

```shell
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

```json
{
  "mcpServers": {
    "shell": {
      "command": "uv",
      "args": [
        "--directory",
        ".",
        "run",
        "mcp-shell-server"
      ],
      "env": {
        "ALLOW_COMMANDS": "ls,cat,pwd,grep,wc,touch,find"
      }
    },
  }
}
```

#### Installation

```bash
pip install mcp-shell-server
```

## Usage

### Starting the Server

#### stdio Mode (default)

```bash
# Basic usage (stdio mode)
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server
# Or using the alias
ALLOWED_COMMANDS="ls,cat,echo" uvx mcp-shell-server

# Explicitly specify stdio mode
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server stdio
```

#### SSE Mode

Start the server in Server-Sent Events (SSE) mode:

```bash
# With default settings (host: 127.0.0.1, port: 8000)
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse

# With custom host and port
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse --host 0.0.0.0 --port 9000

# With custom web path
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse --web-path /shell-web
```

#### Streamable HTTP Mode

Start the server in streamable HTTP mode:

```bash
# With default settings (host: 127.0.0.1, port: 8000, path: /mcp)
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http

# With custom host, port and path
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http --host 0.0.0.0 --port 9000 --path /shell-api

# With custom web path
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http --web-path /shell-web
```

### Starting the Web Interface

The server includes a web management interface for monitoring and managing background processes:

```bash
# Start with default settings (port 5000)
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web

# Specify custom port
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --port 8080

# Running on a specific host
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --host 127.0.0.1

# With URL prefix (for reverse proxy setups)
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --url-prefix /shell
```

### Building Standalone Executable

You can build a standalone executable file that doesn't require Python runtime:

```bash
# Simple build with default settings
uv run --extra dev python build_executable.py

# Build with HTTP proxy (useful if you need to download C compiler)
uv run --extra dev python build_executable.py --proxy http://your-proxy:port

# Quick build with minimal optimizations (faster build time)
uv run --extra dev python build_executable.py --quick

# Parallel compilation to speed up the build
uv run --extra dev python build_executable.py --jobs 8

# Testing mode (shows what will be done without executing)
uv run --extra dev python build_executable.py --test

# Verify an existing executable
uv run --extra dev python build_executable.py --verify
```

The output executable will be located in `dist/executable/mcp-shell-server.exe` (on Windows) or `dist/executable/mcp-shell-server` (on Linux/macOS).

### Environment Variables

The `ALLOW_COMMANDS` (or its alias `ALLOWED_COMMANDS`) environment variable specifies which commands are allowed to be executed. Commands can be separated by commas with optional spaces around them.

Valid formats for ALLOW_COMMANDS or ALLOWED_COMMANDS:

```bash
ALLOW_COMMANDS="ls,cat,echo"          # Basic format
ALLOWED_COMMANDS="ls ,echo, cat"      # With spaces (using alias)
ALLOW_COMMANDS="ls,  cat  , echo"     # Multiple spaces
```

#### Configurable Environment Variables

You can customize the behavior of the MCP Shell Server using the following environment variables:

| Environment Variable | Description | Default Value | Example |
|---------------------|-------------|---------------|---------|
| ALLOW_COMMANDS | List of allowed commands (comma separated) | (empty - no commands allowed) | `ALLOW_COMMANDS="ls,cat,echo,npm,python"` |
| ALLOWED_COMMANDS | Alias for ALLOW_COMMANDS, merged with it | (empty) | `ALLOWED_COMMANDS="git,docker,curl"` |
| PROCESS_RETENTION_SECONDS | Time to retain completed processes before cleanup (seconds) | 3600 (1 hour) | `PROCESS_RETENTION_SECONDS=86400` |
| DEFAULT_ENCODING | Default character encoding for process output | System terminal encoding or utf-8 | `DEFAULT_ENCODING=gbk` |
| COMSPEC | Command processor path on Windows | cmd.exe | `COMSPEC=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` |
| SHELL | Shell program path on Unix/Linux | /bin/sh | `SHELL=/bin/bash` |

#### Server Startup Examples

**Basic startup with minimal permissions:**
```bash
ALLOW_COMMANDS="ls,cat,pwd" uvx mcp-shell-server
```

**Development environment with extended permissions:**
```bash
ALLOW_COMMANDS="ls,cat,pwd,grep,wc,touch,find" \
ALLOWED_COMMANDS="npm,python,git" \
PROCESS_RETENTION_SECONDS=86400 \
uvx mcp-shell-server
```

**Production environment with custom encoding and longer process retention:**
```bash
ALLOW_COMMANDS="ls,cat,echo,find,grep" \
DEFAULT_ENCODING=utf-8 \
PROCESS_RETENTION_SECONDS=172800 \
uvx mcp-shell-server
```

**Windows environment with PowerShell:**
```bash
set ALLOW_COMMANDS=dir,type,echo,findstr
set COMSPEC=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
uvx mcp-shell-server
```

## Server Modes

The server supports three different operation modes:

### stdio Mode (Default)

Uses standard input/output for communication, ideal for integration with Claude.app and other MCP clients.

### SSE Mode

Server-Sent Events mode allows the server to push updates to clients over HTTP. This is useful for web-based integrations and real-time updates.

Command-line options:
- `--host`: Server host address (default: 127.0.0.1)
- `--port`: Server port (default: 8000) 
- `--web-path`: Web interface path (default: /web)

### Streamable HTTP Mode

Provides a HTTP API endpoint for communication. This mode is suitable for RESTful API integrations.

Command-line options:
- `--host`: Server host address (default: 127.0.0.1)
- `--port`: Server port (default: 8000)
- `--path`: API endpoint path (default: /mcp)
- `--web-path`: Web interface path (default: /web)

## Web Management Interface

The web interface provides a convenient way to monitor and manage background processes:

### Features

* **Process List View**: See all running and completed processes
* **Process Detail View**: Examine detailed information about a specific process
* **Real-time Output Viewing**: Monitor stdout and stderr of running processes
* **Process Control**: Stop, terminate, and clean up processes
* **Filtering**: Filter processes by status or labels

### Screenshots

(Insert screenshots here when available)

### Accessing the Web Interface

By default, the web interface is accessible at http://localhost:5000 when started with the `--web` flag.

## API Reference

### Tool: shell_execute

Execute a shell command and return the results.

#### Request Format

```json
{
    "command": ["ls", "-l", "/tmp"],
    "directory": "/path/to/working/directory",
    "stdin": "Optional input data",
    "timeout": 30,
    "encoding": "utf-8"
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "**exit with 0**"
},
{
    "type": "text",
    "text": "---\nstdout:\n---\ncommand output here\n"
},
{
    "type": "text",
    "text": "---\nstderr:\n---\nerror output here\n"
}
```

#### Request Arguments

| Field     | Type       | Required | Description                                   |
|-----------|------------|----------|-----------------------------------------------|
| command   | string[]   | Yes      | Command and its arguments as array elements   |
| directory | string     | Yes      | Working directory for command execution       |
| stdin     | string     | No       | Input to be passed to the command            |
| timeout   | integer    | No       | Maximum execution time in seconds (default: 15) |
| envs      | object     | No       | Additional environment variables for the command |
| encoding  | string     | No       | Character encoding for command output (e.g. 'utf-8', 'gbk', 'cp936') |
| limit_lines | integer  | No       | Maximum number of lines to return in each TextContent (default: 500) |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Command output information including exit status, stdout and stderr |

### Tool: shell_bg_start

Start a background process for long-running commands.

#### Request Format

```json
{
    "command": ["npm", "start"],
    "directory": "/path/to/project",
    "description": "Start Node.js application",
    "labels": ["nodejs", "app"],
    "stdin": "Optional input data",
    "envs": {
        "NODE_ENV": "development"
    },
    "encoding": "utf-8",
    "timeout": 3600
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "Started background process with ID: 123"
}
```

#### Request Arguments

| Field       | Type       | Required | Description                                   |
|-------------|------------|----------|-----------------------------------------------|
| command     | string[]   | Yes      | Command and its arguments as array elements   |
| directory   | string     | Yes      | Working directory for command execution       |
| description | string     | Yes      | Description of the command                    |
| labels      | string[]   | No       | Labels to categorize the command              |
| stdin       | string     | No       | Input to be passed to the command            |
| envs        | object     | No       | Additional environment variables for the command |
| encoding    | string     | No       | Character encoding for command output        |
| timeout     | integer    | No       | Maximum execution time in seconds             |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Confirmation message with process ID        |

### Tool: shell_bg_list

List running or completed background processes.

#### Request Format

```json
{
    "labels": ["nodejs"],
    "status": "running"
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "ID | STATUS | START TIME | COMMAND | DESCRIPTION | LABELS\n---------\n123 | running | 2023-05-06 14:30:00 | npm start | Start Node.js app | nodejs"
}
```

#### Request Arguments

| Field     | Type       | Required | Description                                   |
|-----------|------------|----------|-----------------------------------------------|
| labels    | string[]   | No       | Filter processes by labels                    |
| status    | string     | No       | Filter by status ('running', 'completed', 'failed', 'terminated', 'error') |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Formatted table of processes                |

### Tool: shell_bg_stop

Stop a running background process.

#### Request Format

```json
{
    "pid": 123,
    "force": false
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "Process 123 has been gracefully stopped\nCommand: npm start\nDescription: Start Node.js application"
}
```

#### Request Arguments

| Field       | Type       | Required | Description                                   |
|-------------|------------|----------|-----------------------------------------------|
| pid         | integer    | Yes      | ID of the process to stop                     |
| force       | boolean    | No       | Whether to force stop the process (default: false) |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Confirmation message with process details   |

### Tool: shell_bg_logs

Get output from a background process.

#### Request Format

```json
{
    "pid": 123,
    "tail": 100,
    "since": "2023-05-06T14:30:00",
    "until": "2023-05-06T15:30:00",
    "with_stdout": true,
    "with_stderr": true,
    "add_time_prefix": true,
    "time_prefix_format": "%Y-%m-%d %H:%M:%S.%f",
    "follow_seconds": 5,
    "limit_lines": 500
}
```

#### Response Format

```json
[
    {
        "type": "text",
        "text": "**Process 123 (status: running)**\nCommand: npm start\nDescription: Start Node.js application\nStatus: Process is still running"
    },
    {
        "type": "text",
        "text": "---\nstdout: 5 lines\n---\n[2023-05-06 14:35:27.123456] Server started on port 3000\n[2023-05-06 14:36:01.789012] Connected to database\n"
    },
    {
        "type": "text",
        "text": "---\nstderr: 1 line\n---\n[2023-05-06 14:35:26.654321] Warning: Configuration file not found\n"
    }
]
```

#### Request Arguments

| Field              | Type       | Required | Description                                   |
|--------------------|------------|----------|-----------------------------------------------|
| pid                | integer    | Yes      | ID of the process to get output from          |
| tail               | integer    | No       | Number of lines to show from the end          |
| since              | string     | No       | Show logs since timestamp (ISO format e.g. '2023-05-06T14:30:00') |
| until              | string     | No       | Show logs until timestamp (ISO format e.g. '2023-05-06T15:30:00') |
| with_stdout        | boolean    | No       | Show standard output (default: true)          |
| with_stderr        | boolean    | No       | Show error output (default: false)            |
| add_time_prefix    | boolean    | No       | Add timestamp prefix to each output line (default: true) |
| time_prefix_format | string     | No       | Format for timestamp prefix (default: "%Y-%m-%d %H:%M:%S.%f") |
| follow_seconds     | integer    | No       | Wait for specified seconds to get new logs (default: 1)   |
| limit_lines        | integer    | No       | Maximum number of lines to return in each TextContent (default: 500) |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Process information and output with optional timestamps |

### Tool: shell_bg_clean

Clean up completed or failed background processes.

#### Request Format

```json
{
    "pids": [123, 456]
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "**Successfully cleaned 1 processes:**\n- PID: 123 | Command: npm start\n\n**Unable to clean 1 running processes:**\nNote: Cannot clean running processes. Stop them first with `shell_bg_stop()`.\n- PID: 456 | Command: node server.js\n\n**Failed to clean 1 processes:**\n- PID: 789 | Reason: Process not found"
}
```

#### Request Arguments

| Field       | Type       | Required | Description                                   |
|-------------|------------|----------|-----------------------------------------------|
| pids        | integer[]  | Yes      | List of process IDs to clean up               |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Formatted table of cleanup results          |

### Tool: shell_bg_detail

Get detailed information about a specific background process.

#### Request Format

```json
{
    "pid": 123
}
```

#### Response Format

```json
{
    "type": "text",
    "text": "### Process Details: 123\n\n#### Basic Information\n- **Status**: completed\n- **Command**: `npm start`\n- **Description**: Start Node.js application\n- **Labels**: nodejs, app\n\n#### Timing\n- **Started**: 2023-05-06 14:30:00\n- **Ended**: 2023-05-06 14:35:27\n- **Duration**: 0:05:27\n\n#### Execution\n- **Working Directory**: /path/to/project\n- **Exit Code**: 0\n\n#### Output Information\n- Use `shell_bg_logs` tool to view process output\n- Example: `shell_bg_logs(pid=123)`"
}
```

#### Request Arguments

| Field       | Type       | Required | Description                                   |
|-------------|------------|----------|-----------------------------------------------|
| pid         | integer    | Yes      | ID of the process to get details for          |

#### Response Fields

| Field     | Type    | Description                                |
|-----------|---------|---------------------------------------------|
| type      | string  | Always "text"                              |
| text      | string  | Formatted detailed information about the process |

## Security

The server implements several security measures:

1. **Command Whitelisting**: Only explicitly allowed commands can be executed
2. **Shell Operator Validation**: Commands after shell operators (;, &&, ||, |) are also validated against the whitelist
3. **No Shell Injection**: Commands are executed directly without shell interpretation

## Development

### Setting up Development Environment

1. Clone the repository

```bash
git clone https://github.com/yourusername/mcp-shell-server.git
cd mcp-shell-server
```

2. Install dependencies including test requirements

```bash
pip install -e ".[test]"
```

### Running Tests

```bash
pytest
```

## Requirements

* Python 3.11 or higher
* mcp>=1.1.0

## License

MIT License - See LICENSE file for details
