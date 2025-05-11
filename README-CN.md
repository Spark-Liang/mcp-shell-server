[English](README.md) | [中文](README-CN.md)

# MCP Shell Server

[![codecov](https://codecov.io/gh/tumf/mcp-shell-server/branch/main/graph/badge.svg)](https://codecov.io/gh/tumf/mcp-shell-server)

一个实现模型上下文协议（MCP）的安全Shell命令执行服务器。该服务器允许远程执行白名单中的shell命令，并支持stdin输入。

<a href="https://glama.ai/mcp/servers/rt2d4pbn22"><img width="380" height="200" src="https://glama.ai/mcp/servers/rt2d4pbn22/badge" alt="mcp-shell-server MCP server" /></a>

## 功能特点

* **安全的命令执行**：只有白名单中的命令才能被执行
* **标准输入支持**：通过stdin向命令传递输入
* **全面的输出信息**：返回stdout、stderr、退出状态和执行时间
* **Shell操作符安全**：验证shell操作符（; , &&, ||, |）后的命令是否在白名单中
* **超时控制**：设置命令的最大执行时间
* **后台进程管理**：在后台运行长时间运行的命令并管理它们
* **Web管理界面**：通过Web UI监控和管理后台进程
* **多种服务器模式**：支持stdio（默认）、SSE和streamable HTTP模式

## 在Claude.app中的MCP客户端设置

### 发布版本

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

### 本地版本

#### 配置

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

#### 安装

```bash
pip install mcp-shell-server
```

## 使用方法

### 启动服务器

#### stdio模式（默认）

```bash
# 基本用法（stdio模式）
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server
# 或者使用别名
ALLOWED_COMMANDS="ls,cat,echo" uvx mcp-shell-server

# 明确指定stdio模式
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server stdio
```

#### SSE模式

以服务器发送事件（SSE）模式启动服务器：

```bash
# 使用默认设置（主机：127.0.0.1，端口：8000）
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse

# 使用自定义主机和端口
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse --host 0.0.0.0 --port 9000

# 使用自定义Web路径
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server sse --web-path /shell-web
```

#### Streamable HTTP模式

以可流式HTTP模式启动服务器：

```bash
# 使用默认设置（主机：127.0.0.1，端口：8000，路径：/mcp）
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http

# 使用自定义主机、端口和路径
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http --host 0.0.0.0 --port 9000 --path /shell-api

# 使用自定义Web路径
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server http --web-path /shell-web
```

### 启动Web界面

服务器包含一个用于监控和管理后台进程的Web管理界面：

```bash
# 使用默认设置启动（端口5000）
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web

# 指定自定义端口
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --port 8080

# 在特定主机上运行
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --host 127.0.0.1

# 使用URL前缀（适用于反向代理设置）
ALLOW_COMMANDS="ls,cat,echo" uvx mcp-shell-server --web --url-prefix /shell
```

### 构建独立可执行文件

你可以构建一个不依赖Python运行时的独立可执行文件:

```bash
# 默认设置的简单构建
uv run --extra dev python build_executable.py

# 使用HTTP代理构建（如果需要下载C编译器时很有用）
uv run --extra dev python build_executable.py --proxy http://your-proxy:port

# 快速构建模式（减少优化，加快构建时间）
uv run --extra dev python build_executable.py --quick

# 并行编译加速构建
uv run --extra dev python build_executable.py --jobs 8

# 测试模式（显示将要执行的操作但不实际执行）
uv run --extra dev python build_executable.py --test

# 验证已存在的可执行文件
uv run --extra dev python build_executable.py --verify
```

生成的可执行文件将位于`dist/executable/mcp-shell-server.exe`（Windows系统）或`dist/executable/mcp-shell-server`（Linux/macOS系统）。

### 环境变量

`ALLOW_COMMANDS`（或其别名`ALLOWED_COMMANDS`）环境变量指定了允许执行的命令。命令可以用逗号分隔，逗号周围可以有可选的空格。

ALLOW_COMMANDS或ALLOWED_COMMANDS的有效格式：

```bash
ALLOW_COMMANDS="ls,cat,echo"          # 基本格式
ALLOWED_COMMANDS="ls ,echo, cat"      # 带空格（使用别名）
ALLOW_COMMANDS="ls,  cat  , echo"     # 多个空格
```

#### 可配置的环境变量

您可以使用以下环境变量自定义MCP Shell Server的行为：

| 环境变量 | 描述 | 默认值 | 示例 |
|--------|------|--------|------|
| ALLOW_COMMANDS | 允许执行的命令列表（逗号分隔） | （空 - 不允许任何命令） | `ALLOW_COMMANDS="ls,cat,echo,npm,python"` |
| ALLOWED_COMMANDS | ALLOW_COMMANDS的别名，与之合并使用 | （空） | `ALLOWED_COMMANDS="git,docker,curl"` |
| PROCESS_RETENTION_SECONDS | 清理前保留已完成进程的时间（秒） | 3600（1小时） | `PROCESS_RETENTION_SECONDS=86400` |
| DEFAULT_ENCODING | 进程输出的默认字符编码 | 系统终端编码或utf-8 | `DEFAULT_ENCODING=gbk` |
| COMSPEC | Windows系统上的命令处理程序路径 | cmd.exe | `COMSPEC=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` |
| SHELL | Unix/Linux系统上的shell程序路径 | /bin/sh | `SHELL=/bin/bash` |

#### 服务器启动示例

**基本启动（最小权限）：**
```bash
ALLOW_COMMANDS="ls,cat,pwd" uvx mcp-shell-server
```

**开发环境（扩展权限）：**
```bash
ALLOW_COMMANDS="ls,cat,pwd,grep,wc,touch,find" \
ALLOWED_COMMANDS="npm,python,git" \
PROCESS_RETENTION_SECONDS=86400 \
uvx mcp-shell-server
```

**生产环境（自定义编码和更长的进程保留时间）：**
```bash
ALLOW_COMMANDS="ls,cat,echo,find,grep" \
DEFAULT_ENCODING=utf-8 \
PROCESS_RETENTION_SECONDS=172800 \
uvx mcp-shell-server
```

**Windows环境（使用PowerShell）：**
```bash
set ALLOW_COMMANDS=dir,type,echo,findstr
set COMSPEC=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
uvx mcp-shell-server
```

## 服务器模式

服务器支持三种不同的运行模式：

### stdio模式（默认）

使用标准输入/输出进行通信，非常适合与Claude.app和其他MCP客户端集成。

### SSE模式

服务器发送事件（Server-Sent Events）模式允许服务器通过HTTP向客户端推送更新。这对于基于Web的集成和实时更新非常有用。

命令行选项：
- `--host`：服务器主机地址（默认：127.0.0.1）
- `--port`：服务器端口（默认：8000）
- `--web-path`：Web界面路径（默认：/web）

### Streamable HTTP模式

提供HTTP API端点进行通信。此模式适用于RESTful API集成。

命令行选项：
- `--host`：服务器主机地址（默认：127.0.0.1）
- `--port`：服务器端口（默认：8000）
- `--path`：API端点路径（默认：/mcp）
- `--web-path`：Web界面路径（默认：/web）

## Web管理界面

Web界面提供了一种方便的方式来监控和管理后台进程：

### 功能特点

* **进程列表视图**：查看所有正在运行和已完成的进程
* **进程详情视图**：检查特定进程的详细信息
* **实时输出查看**：监控正在运行进程的stdout和stderr
* **进程控制**：停止、终止和清理进程
* **过滤功能**：按状态或标签过滤进程

### 截图

（可用时插入截图）

### 访问Web界面

默认情况下，使用`--web`标志启动时，Web界面可在http://localhost:5000访问。

## API参考

### 工具：shell_execute

执行shell命令并返回结果。

#### 请求格式

```json
{
    "command": ["ls", "-l", "/tmp"],
    "directory": "/path/to/working/directory",
    "stdin": "可选的输入数据",
    "timeout": 30,
    "encoding": "utf-8"
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "**exit with 0**"
},
{
    "type": "text",
    "text": "---\nstdout:\n---\n命令输出内容\n"
},
{
    "type": "text",
    "text": "---\nstderr:\n---\n错误输出内容\n"
}
```

#### 请求参数

| 字段      | 类型       | 必需  | 描述                                      |
|----------|------------|------|------------------------------------------|
| command  | string[]   | 是   | 命令及其参数作为数组元素                     |
| directory| string     | 是   | 命令执行的工作目录                           |
| stdin    | string     | 否   | 通过stdin传递给命令的输入                    |
| timeout  | integer    | 否   | 最大执行时间（秒）（默认：15）                 |
| encoding | string     | 否   | 命令输出的字符编码（例如：'utf-8', 'gbk', 'cp936'） |

#### 响应字段

| 字段      | 类型     | 描述                                     |
|----------|---------|------------------------------------------|
| type     | string  | 始终为"text"                              |
| text     | string  | 包含退出状态、stdout和stderr的命令输出信息    |

### 工具：shell_bg_start

启动长时间运行命令的后台进程。

#### 请求格式

```json
{
    "command": ["npm", "start"],
    "directory": "/path/to/project",
    "description": "启动Node.js应用",
    "labels": ["nodejs", "app"],
    "stdin": "可选的输入数据",
    "envs": {
        "NODE_ENV": "development"
    },
    "encoding": "utf-8",
    "timeout": 3600
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "已启动后台进程，ID: process_123"
}
```

#### 请求参数

| 字段        | 类型       | 必需  | 描述                                 |
|------------|------------|------|-------------------------------------|
| command    | string[]   | 是   | 命令及其参数作为数组元素                |
| directory  | string     | 是   | 命令执行的工作目录                     |
| description| string     | 是   | 命令的描述                            |
| labels     | string[]   | 否   | 用于分类命令的标签                     |
| stdin      | string     | 否   | 通过stdin传递给命令的输入              |
| envs       | object     | 否   | 命令的附加环境变量                     |
| encoding   | string     | 否   | 命令输出的字符编码                     |
| timeout    | integer    | 否   | 最大执行时间（秒）                     |

#### 响应字段

| 字段      | 类型     | 描述                           |
|----------|---------|--------------------------------|
| type     | string  | 始终为"text"                    |
| text     | string  | 带有进程ID的确认消息             |

### 工具：shell_bg_list

列出正在运行或已完成的后台进程。

#### 请求格式

```json
{
    "labels": ["nodejs"],
    "status": "running"
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "ID | 状态 | 开始时间 | 命令 | 描述 | 标签\n---------\nprocess_123 | running | 2023-05-06 14:30:00 | npm start | 启动Node.js应用 | nodejs"
}
```

#### 请求参数

| 字段    | 类型      | 必需  | 描述                                     |
|--------|-----------|------|------------------------------------------|
| labels | string[]  | 否   | 按标签过滤进程                             |
| status | string    | 否   | 按状态过滤('running', 'completed', 'failed', 'terminated', 'error') |

#### 响应字段

| 字段   | 类型    | 描述                  |
|-------|---------|----------------------|
| type  | string  | 始终为"text"          |
| text  | string  | 格式化的进程表格        |

### 工具：shell_bg_stop

停止正在运行的后台进程。

#### 请求格式

```json
{
    "process_id": "process_123",
    "force": false
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "进程process_123已被优雅地停止\n命令: npm start\n描述: 启动Node.js应用"
}
```

#### 请求参数

| 字段       | 类型     | 必需  | 描述                               |
|-----------|----------|------|-----------------------------------|
| process_id| string   | 是   | 要停止的进程ID                      |
| force     | boolean  | 否   | 是否强制停止进程（默认：false）       |

#### 响应字段

| 字段   | 类型    | 描述                      |
|-------|---------|--------------------------|
| type  | string  | 始终为"text"              |
| text  | string  | 带有进程详情的确认消息      |

### 工具：shell_bg_logs

获取后台进程的输出。

#### 请求格式

```json
{
    "process_id": "process_123",
    "tail": 100,
    "since": "2023-05-06T14:30:00",
    "until": "2023-05-06T15:30:00",
    "with_stdout": true,
    "with_stderr": true,
    "add_time_prefix": true,
    "time_prefix_format": "%Y-%m-%d %H:%M:%S.%f",
    "follow_seconds": 5
}
```

#### 响应格式

```json
[
    {
        "type": "text",
        "text": "**进程process_123（状态：running）**\n命令: npm start\n描述: 启动Node.js应用\n状态: 进程仍在运行"
    },
    {
        "type": "text",
        "text": "---\nstdout: 5行\n---\n[2023-05-06 14:35:27.123456] 服务器在端口3000上启动\n[2023-05-06 14:36:01.789012] 已连接到数据库\n"
    },
    {
        "type": "text",
        "text": "---\nstderr: 1行\n---\n[2023-05-06 14:35:26.654321] 警告：未找到配置文件\n"
    }
]
```

#### 请求参数

| 字段               | 类型      | 必需  | 描述                                       |
|-------------------|-----------|------|-------------------------------------------|
| process_id        | string    | 是   | 获取输出的进程ID                            |
| tail              | integer   | 否   | 从末尾显示的行数                             |
| since             | string    | 否   | 显示从该时间戳开始的日志（例如：'2023-05-06T14:30:00'） |
| until             | string    | 否   | 显示到该时间戳为止的日志（例如：'2023-05-06T15:30:00'） |
| with_stdout       | boolean   | 否   | 显示标准输出（默认：true）                    |
| with_stderr       | boolean   | 否   | 显示错误输出（默认：false）                   |
| add_time_prefix   | boolean   | 否   | 为每行输出添加时间戳前缀（默认：true）          |
| time_prefix_format| string    | 否   | 时间戳前缀的格式（默认："%Y-%m-%d %H:%M:%S.%f"） |
| follow_seconds    | integer   | 否   | 等待指定秒数以获取新日志                       |

#### 响应字段

| 字段   | 类型    | 描述                              |
|-------|---------|----------------------------------|
| type  | string  | 始终为"text"                      |
| text  | string  | 进程信息和带有可选时间戳的输出       |

### 工具：shell_bg_clean

清理已完成或失败的后台进程。

#### 请求格式

```json
{
    "process_ids": ["process_123", "process_456"]
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "进程ID | 状态 | 消息\n---------\nprocess_123 | SUCCESS | 进程清理成功\nprocess_456 | FAILED | 进程仍在运行中"
}
```

#### 请求参数

| 字段        | 类型       | 必需  | 描述                         |
|------------|------------|------|----------------------------|
| process_ids| string[]   | 是   | 要清理的进程ID列表            |

#### 响应字段

| 字段   | 类型    | 描述                    |
|-------|---------|------------------------|
| type  | string  | 始终为"text"            |
| text  | string  | 格式化的清理结果表格      |

### 工具：shell_bg_detail

获取特定后台进程的详细信息。

#### 请求格式

```json
{
    "process_id": "process_123"
}
```

#### 响应格式

```json
{
    "type": "text",
    "text": "### 进程详情: process_123\n\n#### 基本信息\n- **状态**: completed\n- **命令**: `npm start`\n- **描述**: 启动Node.js应用\n- **标签**: nodejs, app\n\n#### 时间信息\n- **开始时间**: 2023-05-06 14:30:00\n- **结束时间**: 2023-05-06 14:35:27\n- **持续时间**: 0:05:27\n\n#### 执行信息\n- **工作目录**: /path/to/project\n- **退出码**: 0\n\n#### 输出信息\n- 使用`shell_bg_logs`工具查看进程输出\n- 示例: `shell_bg_logs(process_id='process_123')`"
}
```

#### 请求参数

| 字段       | 类型     | 必需  | 描述                   |
|-----------|----------|------|------------------------|
| process_id| string   | 是   | 获取详情的进程ID        |

#### 响应字段

| 字段   | 类型    | 描述                      |
|-------|---------|--------------------------|
| type  | string  | 始终为"text"              |
| text  | string  | 关于进程的格式化详细信息    |

## 安全性

服务器实现了几项安全措施：

1. **命令白名单**：只有明确允许的命令才能执行
2. **Shell操作符验证**：Shell操作符（;, &&, ||, |）后的命令也会与白名单进行验证
3. **无Shell注入**：命令直接执行，不通过shell解释

## 开发

### 设置开发环境

1. 克隆仓库

```bash
git clone https://github.com/yourusername/mcp-shell-server.git
cd mcp-shell-server
```

2. 安装依赖项（包括测试需求）

```bash
pip install -e ".[test]"
```

### 运行测试

```bash
pytest
```

## 系统要求

* Python 3.11或更高版本
* mcp>=1.1.0

## 许可证

MIT许可证 - 详情请参阅LICENSE文件 