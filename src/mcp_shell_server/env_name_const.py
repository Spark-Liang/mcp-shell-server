"""
Environment variable constants used in the MCP Shell Server.

This module defines constants for all environment variables that can be used
to configure the MCP Shell Server.
"""

# Background process manager configuration
PROCESS_RETENTION_SECONDS = "PROCESS_RETENTION_SECONDS"
"""已完成进程的保留时间（秒），超过此时间的进程将被自动清理。
默认值：3600（1小时）
用法：设置为较大的值可以保留进程历史更长时间，便于查看历史记录。当进程终止后，系统会自动安排在此时间后清理进程资源。
例如：export PROCESS_RETENTION_SECONDS=86400  # 保留1天
"""

# Shell executor configuration
COMSPEC = "COMSPEC"
"""Windows系统上使用的命令处理程序路径。
默认值：cmd.exe
用法：通常由系统设置，可以修改为其他shell程序路径。
例如：set COMSPEC=C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe
"""

SHELL = "SHELL"
"""Unix/Linux系统上使用的shell程序路径。
默认值：/bin/sh
用法：通常由系统设置，可以修改为其他shell程序路径。
例如：export SHELL=/bin/bash
"""

DEFAULT_ENCODING = "DEFAULT_ENCODING"
"""进程输出的默认字符编码。
默认值：（按优先级）1. 系统终端编码 2. utf-8
用法：在处理特殊编码输出时可以手动指定。
例如：export DEFAULT_ENCODING=gbk  # 在处理中文Windows系统输出时
"""

# Command validator configuration
ALLOW_COMMANDS = "ALLOW_COMMANDS"
"""允许执行的命令列表，多个命令用逗号分隔。
默认值：空（不允许任何命令）
用法：设置允许执行的命令，提高安全性。
例如：export ALLOW_COMMANDS="ls,cat,echo,npm,python"
"""

ALLOWED_COMMANDS = "ALLOWED_COMMANDS"
"""允许执行的命令列表的别名，与ALLOW_COMMANDS合并使用。
默认值：空
用法：与ALLOW_COMMANDS相同，可以同时使用两个变量来分组管理允许的命令。
例如：export ALLOWED_COMMANDS="git,docker,curl"
"""
