"""FastMCP 实现的 MCP Shell Server"""

import asyncio
import logging
import traceback
import sys
import threading
import socket
import os
from typing import List, Optional, Sequence, Dict, Any, Union
from contextlib import asynccontextmanager
from datetime import datetime

import click
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent, EmbeddedResource
from pydantic import Field, field_validator, model_validator

from .version import __version__
from .shell_executor import default_shell_executor
from .interfaces import LogEntry
from . import background_process_manager_web as web_server
from .background_process_manager import ProcessStatus
from .env_name_const import DEFAULT_ENCODING

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-shell-server")

# 默认超时时间
DEFAULT_TIMEOUT = 15

DEFAULT_ENCODING_VALUE = os.environ.get(DEFAULT_ENCODING, "utf-8")

# Web服务器线程
web_server_thread = None

def get_free_port() -> int:
    """获取一个可用的随机端口
    
    Returns:
        int: 可用的端口号
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('0.0.0.0', 0))
        return s.getsockname()[1]

def get_local_ip_addresses() -> List[str]:
    """获取本机所有IP地址
    
    Returns:
        List[str]: IP地址列表
    """
    try:
        # 获取主机名
        hostname = socket.gethostname()
        # 获取所有IP地址
        ip_list = []
        # 尝试获取IPv4地址
        try:
            ip_list.append(socket.gethostbyname(hostname))
        except Exception:
            pass
            
        # 尝试获取所有网络接口
        try:
            addresses = socket.getaddrinfo(
                host=hostname, 
                port=None, 
                family=socket.AF_INET  # 只获取IPv4地址
            )
            for addr in addresses:
                ip = addr[4][0]
                if ip not in ip_list and not ip.startswith('127.'):
                    ip_list.append(ip)
        except Exception:
            pass
            
        return ip_list
    except Exception:
        # 如果出现任何错误，返回空列表
        return []

async def _cleanup_background_processes() -> None:
    """清理后台进程"""
    try:
        logger.info("Cleaning up background processes...")
        await default_shell_executor.process_manager.cleanup_all()
        logger.info("Background process cleanup completed.")
    except Exception as cleanup_error:
        logger.error(f"Error during background process cleanup: {cleanup_error}")

def _format_to_number(mix_format_number: Optional[Union[int, float, str]]) -> Optional[Union[int, float]]:
    """将mcp server的数字形式的参数格式化成数字"""
    if mix_format_number is None:
        return None
    if isinstance(mix_format_number, str):
        try:
            return int(mix_format_number)
        except ValueError:
            try:
                return float(mix_format_number)
            except ValueError:
                raise ValueError(f"Invalid value: {mix_format_number}, must be an string in format of integer or a float") 
    return mix_format_number

@asynccontextmanager
async def lifespan(app: FastMCP):
    """服务器生命周期管理"""
    try:
        yield {}
    finally:
        # 服务器关闭时清理后台进程
        await _cleanup_background_processes()

# 创建FastMCP实例
mcp = FastMCP("mcp-shell-server", lifespan=lifespan)

@mcp.tool(
        description=f"""Execute a shell command **in foreground**. Allowed commands:  {",".join(default_shell_executor.allowed_commands)}"""
)
async def shell_execute(
    command: List[str] = Field(
        description="Command and its arguments as array"
    ),
    directory: str = Field(
        description=f"Absolute path to the working directory where the command will be executed. Example: {os.getcwd()}",
        examples=[os.getcwd()]
    ),
    stdin: Optional[str] = Field(
        default=None,
        description="Input to be passed to the command via stdin",
    ),
    timeout: int = Field(
        default=DEFAULT_TIMEOUT,
        description="Maximum execution time in seconds. If None, the command will run indefinitely.",
        ge=0,
    ),
    envs: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional environment variables for the command"
    ),
    encoding: str = Field(
        default=DEFAULT_ENCODING_VALUE,
        description="Character encoding for command output (e.g. 'utf-8', 'gbk', 'cp936')",
    ),
    limit_lines: int = Field(
        default=500,
        description="Maximum number of lines to return in each TextContent",
        ge=1
    )
) -> Sequence[TextContent]:
    
    
    try:
        # 前置检查
        if not command:
            raise ValueError("No command provided")
            
        if not directory:
            raise ValueError("Directory is required")
            
        timeout = _format_to_number(timeout)
        if timeout is not None and timeout <= 0:
            raise ValueError(f"Invalid timeout value: {timeout}, must be a positive number")
            
        # 执行命令
        try:
            result = await asyncio.wait_for(
                default_shell_executor.execute(
                    command, directory, stdin, timeout, envs, encoding
                ),
                timeout=timeout or DEFAULT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise ValueError(f"Command execution timed out after {timeout or DEFAULT_TIMEOUT} seconds")

        if result.get("error"):
            raise ValueError(result["error"])

        content = []
        content.append(TextContent(type="text", text=f"**exit with {result.get('status')}**"))

        # 添加stdout（如果存在）
        if result.get("stdout"):
            stdout_lines = result.get("stdout").splitlines()
            total_stdout_lines = len(stdout_lines)
            
            if total_stdout_lines > limit_lines:
                # 截断超过限制的行数
                truncated_stdout = "\n".join(stdout_lines[:limit_lines])
                truncated_message = f"\n... (output truncated, showing {limit_lines} of {total_stdout_lines} lines)"
                
                content.append(TextContent(
                    type="text", 
                    text=f"""---
stdout: (truncated, {limit_lines}/{total_stdout_lines} lines shown)
---
{truncated_stdout}
{truncated_message}
"""
                ))
            else:
                content.append(TextContent(
                    type="text", 
                    text=f"""---
stdout:
---
{result.get("stdout")}
"""
                ))

        # 添加stderr（如果存在且不包含特定消息）
        stderr = result.get("stderr")
        if stderr and "cannot set terminal process group" not in stderr:
            stderr_lines = stderr.splitlines()
            total_stderr_lines = len(stderr_lines)
            
            if total_stderr_lines > limit_lines:
                # 截断超过限制的行数
                truncated_stderr = "\n".join(stderr_lines[:limit_lines])
                truncated_message = f"\n... (output truncated, showing {limit_lines} of {total_stderr_lines} lines)"
                
                content.append(TextContent(
                    type="text", 
                    text=f"""---
stderr: (truncated, {limit_lines}/{total_stderr_lines} lines shown)
---
{truncated_stderr}
{truncated_message}
"""
                ))
            else:
                content.append(TextContent(
                    type="text", 
                    text=f"""---
stderr:
---
{stderr}
"""
                ))

        return content
    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        logger.error(traceback.format_exc())
        raise RuntimeError(f"Error executing command: {str(e)}")

@mcp.tool(
        description=f"""Start a command **in background** and return its ID. Allowed commands: {",".join(default_shell_executor.allowed_commands)}"""
)
async def shell_bg_start(
    command: List[str] = Field(
        description="Command and its arguments as array"
    ),
    directory: str = Field(
        description="Absolute path to the working directory where the command will be executed"
    ),
    description: str = Field(
        description="Description of the command (required)"
    ),
    labels: Optional[List[str]] = Field(
        default=None,
        description="Labels to categorize the command"
    ),
    stdin: Optional[str] = Field(
        default=None,
        description="Input to be passed to the command via stdin",
        
    ),
    envs: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional environment variables for the command"
    ),
    encoding: str = Field(
        default=DEFAULT_ENCODING_VALUE,
        description="Character encoding for command output (e.g. 'utf-8', 'gbk', 'cp936')",
    ),
    timeout: int = Field(
        default=DEFAULT_TIMEOUT,
        description="Maximum execution time in seconds. If None, the command will run indefinitely.",
        ge=0,
        
    )
) -> Sequence[TextContent]:
    timeout = _format_to_number(timeout)
    if timeout is not None and timeout <= 0:
        raise ValueError(f"Invalid timeout value: {timeout}, must be a positive number")
    
    try:
        # 验证命令不为空
        if not command:
            raise ValueError("Command cannot be empty")
            
        # 验证目录存在
        if not os.path.isdir(directory):
            raise ValueError(f"Directory '{directory}' does not exist")
            
        # 使用 ShellExecutor 启动后台进程
        pid = await default_shell_executor.async_execute(
            command=command,
            directory=directory,
            description=description,
            labels=labels,
            stdin=stdin,
            envs=envs,
            encoding=encoding,
            timeout=timeout
        )
        
        return [TextContent(
            type="text",
            text=f"Started background process with ID: {pid}"
        )]
    except Exception as e:
        logger.error(f"Error starting background process: {e}")
        raise ValueError(f"Error starting background process: {str(e)}")

@mcp.tool()
async def shell_bg_list(
    labels: Optional[List[str]] = Field(
        default=None,
        description="Filter processes by labels"
    ),
    status: Optional[str] = Field(
        default=None,
        description="Filter processes by status ({})".format(", ".join([f"'{s.value}'" for s in ProcessStatus]))
    )
) -> Sequence[TextContent]:
    """List background processes with optional label and status filtering"""
    
    try:
        # 验证状态值
        if status and status not in [s.value for s in ProcessStatus]:
            raise ValueError(f"Status must be one of: {', '.join([s.value for s in ProcessStatus])}")
            
        # 将状态字符串转换为枚举类型
        status_enum = ProcessStatus(status) if status else None
        
        # 使用 ShellExecutor 获取进程列表
        processes = await default_shell_executor.list_processes(labels=labels, status=status_enum)
        
        if not processes:
            return [TextContent(
                type="text",
                text="No background processes found"
            )]
            
        # 格式化输出
        lines = ["ID | STATUS | START TIME | COMMAND | DESCRIPTION | LABELS"]
        lines.append("-" * 100)
        
        for proc in processes:
            # 获取进程ID（假设格式化后会有一个进程ID）
            pid_short = proc.shell_cmd.split()[0][:8] if len(proc.shell_cmd.split()) > 0 else "N/A"
            
            # 获取命令字符串
            cmd_str = proc.shell_cmd
            if len(cmd_str) > 30:
                cmd_str = cmd_str[:27] + "..."
                
            # 获取标签字符串
            labels_str = ", ".join(proc.labels) if proc.labels else ""
            
            # 格式化开始时间
            start_time_str = proc.start_time.strftime("%Y-%m-%d %H:%M:%S")
            
            lines.append(f"{pid_short} | {proc.status.value} | {start_time_str} | {cmd_str} | {proc.description} | {labels_str}")
            
        return [TextContent(
            type="text",
            text="\n".join(lines)
        )]
    except Exception as e:
        logger.error(f"Error listing background processes: {e}")
        raise ValueError(f"Error listing background processes: {str(e)}")

@mcp.tool()
async def shell_bg_stop(
    pid: int = Field(
        description="ID of the process to stop"
    ),
    force: bool = Field(
        default=False,
        description="Whether to force stop the process"
    )
) -> Sequence[TextContent]:
    """Stop a background process"""
    
    try:
        # 获取进程信息（用于返回消息）
        process = await default_shell_executor.get_process(pid)
        if not process:
            raise ValueError(f"Process with ID {pid} not found")
            
        # 构建描述字符串
        cmd_str = process.command if hasattr(process, 'command') else process.process_info.shell_cmd
        if len(cmd_str) > 30:
            cmd_str = cmd_str[:27] + "..."
            
        # 获取进程描述
        description = process.description if hasattr(process, 'description') else process.process_info.description
            
        # 使用 ShellExecutor 停止进程
        await default_shell_executor.stop_process(pid, force)
        
        return [TextContent(
            type="text",
            text=f"Process {pid} has been {'forcefully terminated' if force else 'gracefully stopped'}\nCommand: {cmd_str}\nDescription: {description}"
        )]
    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        logger.error(f"Error stopping background process: {e}")
        raise ValueError(f"Error stopping background process: {str(e)}")

@mcp.tool()
async def shell_bg_logs(
    pid: int = Field(
        description="ID of the process to get output from"
    ),
    tail: Optional[int] = Field(
        default=None,
        description="Number of lines to show from the end",
        gt=0  # greater than 0
    ),
    since: Optional[datetime] = Field(
        default=None,
        description="Show logs since timestamp (e.g. '2021-01-01T00:00:00')"
    ),
    until: Optional[datetime] = Field(
        default=None,
        description="Show logs until timestamp (e.g. '2021-01-01T00:00:00')"
    ),
    with_stdout: bool = Field(
        default=True,
        description="Show standard output"
    ),
    with_stderr: bool = Field(
        default=False,
        description="Show error output"
    ),
    add_time_prefix: bool = Field(
        default=True,
        description="Add timestamp prefix to each output line"
    ),
    time_prefix_format: str = Field(
        default="%Y-%m-%d %H:%M:%S.%f",
        description="Format of the timestamp prefix, using strftime format"
    ),
    follow_seconds: int = Field(
        default=1,
        description="Wait for the specified number of seconds to get new logs. If 0, return immediately.",
        ge=0
    ),
    limit_lines: int = Field(
        default=500,
        description="Maximum number of lines to return in each TextContent",
        ge=1
    )
) -> Sequence[TextContent]:
    """Get output from a background process, similar to 'docker logs'"""
    
    follow_seconds = _format_to_number(follow_seconds)
    if follow_seconds is not None and follow_seconds < 0:
        raise ValueError(f"Invalid follow_seconds value: {follow_seconds}, must be a non-negative number")
    
    def _format_process_output(
        output: List[LogEntry], 
        stream_name: str, 
        add_time_prefix: bool, 
        time_prefix_format: str,
        limit_lines: int
    ) -> TextContent:
        """格式化进程输出"""
        if output:
            formatted_lines = []
            for line in output:
                if add_time_prefix:
                    timestamp = line.timestamp.strftime(time_prefix_format)
                    formatted_lines.append(f"[{timestamp}] {line.text}")
                else:
                    formatted_lines.append(line.text)
            
            total_lines = len(formatted_lines)
            
            # 处理行数限制
            if total_lines > limit_lines:
                # 截断行数
                truncated_lines = formatted_lines[:limit_lines]
                output_text = "\n".join(truncated_lines)
                truncated_message = f"\n... (output truncated, showing {limit_lines} of {total_lines} lines)"
                
                return TextContent(
                    type="text", 
                    text=f"---\n{stream_name}: (truncated, {limit_lines}/{total_lines} lines shown)\n---\n{output_text}{truncated_message}\n"
                )
            else:
                output_text = "\n".join(formatted_lines)
                return TextContent(
                    type="text", 
                    text=f"---\n{stream_name}: {total_lines} lines\n---\n{output_text}\n"
                )
        else:
            return TextContent(
                type="text",
                text=f"---\n{stream_name}: 0 lines\n---\n"
            )
    
    try:
        # 获取进程对象
        process = await default_shell_executor.get_process(pid)
        if not process:
            raise ValueError(f"Process with ID {pid} not found")
            
        # 获取进程信息
        status_value = (
            process.status.value 
            if hasattr(process, 'status') 
            else "unknown"
        )
        
        cmd_str = (
            process.command 
            if hasattr(process, 'command') 
            else getattr(process, 'shell_cmd', 'Unknown command')
        )
        
        # 截断过长的命令
        if len(cmd_str) > 50:
            cmd_str = cmd_str[:47] + "..."
            
        # 添加进程信息作为第一个TextContent
        status_info = f"**Process {pid} (status: {status_value})**\n"
        status_info += f"Command: {cmd_str}\n"
        
        # 添加标签信息（如果有）
        if hasattr(process, 'labels') and process.labels:
            status_info += f"Labels: {', '.join(process.labels)}\n"
        
        # 添加执行时间信息
        if hasattr(process, 'start_time'):
            start_time = process.start_time.strftime('%Y-%m-%d %H:%M:%S')
            status_info += f"Started at: {start_time}\n"
            
            if hasattr(process, 'end_time') and process.end_time:
                end_time = process.end_time.strftime('%Y-%m-%d %H:%M:%S')
                status_info += f"Ended at: {end_time}\n"
                
                # 计算运行时间
                duration = process.end_time - process.start_time
                duration_str = str(duration).split('.')[0]  # 移除微秒部分
                status_info += f"Duration: {duration_str}\n"
        
        # 添加退出码信息（如果有）
        if hasattr(process, 'exit_code') and process.exit_code is not None:
            status_info += f"Exit code: {process.exit_code}\n"
            
        result_content = [TextContent(type="text", text=status_info)]
        
        # 存储初始获取时间和结果
        initial_stdout_output = []
        initial_stderr_output = []
        current_time = datetime.now()
        
        # 获取初始日志
        if with_stdout:
            # 使用 ShellExecutor 获取标准输出
            initial_stdout_output = await default_shell_executor.get_process_output(
                pid=pid,
                tail=tail,
                since=since,
                until=until,
                error=False
            )
            
        if with_stderr:
            # 使用 ShellExecutor 获取错误输出
            initial_stderr_output = await default_shell_executor.get_process_output(
                pid=pid,
                tail=tail,
                since=since,
                until=until,
                error=True
            )
        
        # 如果 follow_seconds > 0，等待并获取新日志
        if follow_seconds and follow_seconds > 0:
            # 等待指定的秒数
            await asyncio.sleep(follow_seconds)
            
            # 获取新的日志（仅获取上次之后的部分）
            new_stdout_output = []
            new_stderr_output = []
            
            if with_stdout:
                new_stdout_output = await default_shell_executor.get_process_output(
                    pid=pid,
                    since=current_time,  # 仅获取初始获取之后的日志
                    until=None,
                    error=False
                )
                
            if with_stderr:
                new_stderr_output = await default_shell_executor.get_process_output(
                    pid=pid,
                    since=current_time,  # 仅获取初始获取之后的日志
                    until=None,
                    error=True
                )
                
            # 合并初始日志和新日志
            stdout_output = initial_stdout_output + new_stdout_output
            stderr_output = initial_stderr_output + new_stderr_output
        else:
            # 不等待，直接使用初始日志
            stdout_output = initial_stdout_output
            stderr_output = initial_stderr_output
        
        # 格式化并添加标准输出
        if with_stdout:
            if stdout_output:
                # 格式化输出
                stdout_content = _format_process_output(
                    stdout_output, 
                    "STDOUT", 
                    add_time_prefix,
                    time_prefix_format,
                    limit_lines
                )
                result_content.append(stdout_content)
            else:
                result_content.append(TextContent(
                    type="text", 
                    text="No standard output available"
                ))
        
        # 格式化并添加错误输出
        if with_stderr:
            if stderr_output:
                # 格式化输出
                stderr_content = _format_process_output(
                    stderr_output, 
                    "STDERR", 
                    add_time_prefix,
                    time_prefix_format,
                    limit_lines
                )
                result_content.append(stderr_content)
            else:
                result_content.append(TextContent(
                    type="text", 
                    text="No error output available"
                ))
                
        # 添加帮助信息
        extra_info_lines = [
            "---",
            "extra infos:",
            "---",
            "**Follow Options:**"
        ]
        
        if follow_seconds > 0:
            extra_info_lines.append(f"- Showing logs with {follow_seconds}s follow time")
            extra_info_lines.append(f"- For longer follow: `shell_bg_logs(pid={pid}, follow_seconds=60" + 
                              (", with_stderr=True" if with_stderr else "") + ")`")
        else:
            extra_info_lines.append("- Showing logs without following (snapshot)")
            extra_info_lines.append(f"- To follow logs: `shell_bg_logs(pid={pid}, follow_seconds=5" + 
                              (", with_stderr=True" if with_stderr else "") + ")`")
        
        result_content.append(TextContent(
            type="text",
            text="\n".join(extra_info_lines)
        ))
            
        return result_content
    except Exception as e:
        logger.error(f"Error getting process output: {e}")
        raise ValueError(f"Error getting process output: {str(e)}")

@mcp.tool()
async def shell_bg_clean(
    pids: List[int] = Field(
        description="要清理的进程ID列表"
    )
) -> Sequence[TextContent]:
    """Clean background processes that have completed or failed"""
    
    # 结果表格
    result_table = {
        "cleaned": [],
        "failed": [],
        "running": []
    }
    
    # 验证进程列表
    if not pids:
        return [TextContent(type="text", text="No process IDs provided to clean up")]
        
    # 尝试清理每个进程
    for pid in pids:
        try:
            # 获取进程信息用于记录
            process = await default_shell_executor.get_process(pid)
            
            if not process:
                result_table["failed"].append({
                    "pid": pid,
                    "reason": "Process not found"
                })
                continue
                
            # 检查进程状态
            is_running = False
            if hasattr(process, 'is_running'):
                is_running = process.is_running()
            elif hasattr(process, 'returncode'):
                is_running = process.returncode is None
                
            if is_running:
                result_table["running"].append({
                    "pid": pid,
                    "command": getattr(process, 'command', 'Unknown command')[:30] + ('...' if len(getattr(process, 'command', '')) > 30 else '')
                })
                continue
            
            # 尝试清理进程
            await default_shell_executor.clean_completed_process(pid)
            
            # 记录成功清理的进程
            result_table["cleaned"].append({
                "pid": pid,
                "command": getattr(process, 'command', 'Unknown command')[:30] + ('...' if len(getattr(process, 'command', '')) > 30 else '')
            })
            
        except Exception as e:
            logger.error(f"Error cleaning process {pid}: {e}")
            result_table["failed"].append({
                "pid": pid,
                "reason": str(e)
            })
            
    # 生成结果消息
    result_lines = []
    
    # 添加成功清理的进程
    if result_table["cleaned"]:
        result_lines.append(f"**Successfully cleaned {len(result_table['cleaned'])} processes:**")
        for proc in result_table["cleaned"]:
            result_lines.append(f"- PID: {proc['pid']} | Command: {proc['command']}")
            
    # 添加运行中的进程
    if result_table["running"]:
        result_lines.append(f"\n**Unable to clean {len(result_table['running'])} running processes:**")
        result_lines.append("Note: Cannot clean running processes. Stop them first with `shell_bg_stop()`.")
        for proc in result_table["running"]:
            result_lines.append(f"- PID: {proc['pid']} | Command: {proc['command']}")
            
    # 添加失败的进程
    if result_table["failed"]:
        result_lines.append(f"\n**Failed to clean {len(result_table['failed'])} processes:**")
        for proc in result_table["failed"]:
            result_lines.append(f"- PID: {proc['pid']} | Reason: {proc['reason']}")
            
    # 如果没有任何处理结果，添加默认消息
    if not result_lines:
        result_lines.append("No processes were processed.")
        
    return [TextContent(type="text", text="\n".join(result_lines))]

@mcp.tool()
async def shell_bg_detail(
    pid: int = Field(
        description="ID of the process to get details for"
    )
) -> Sequence[TextContent]:
    """Get detailed information about a specific background process"""
    
    try:
        # 获取进程
        process = await default_shell_executor.get_process(pid)
        if not process:
            raise ValueError(f"Process {pid} not found")
        
        # 获取进程详细信息
        lines = [f"**Process Details for PID {pid}**"]
        
        # 基本信息
        lines.append("\n**Basic Information:**")
        
        # 命令
        command = getattr(process, 'command', None)
        if command:
            lines.append(f"Command: `{command}`")
        
        # 状态
        status = getattr(process, 'status', None)
        if status:
            lines.append(f"Status: {status.value if hasattr(status, 'value') else status}")
        
        # 目录
        directory = getattr(process, 'directory', None)
        if directory:
            lines.append(f"Working Directory: {directory}")
        
        # 描述
        description = getattr(process, 'description', None)
        if description:
            lines.append(f"Description: {description}")
        
        # 标签
        labels = getattr(process, 'labels', None)
        if labels and len(labels) > 0:
            lines.append(f"Labels: {', '.join(labels)}")
        
        # 时间信息
        lines.append("\n**Timing Information:**")
        
        # 开始时间
        start_time = getattr(process, 'start_time', None)
        if start_time:
            lines.append(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 结束时间
        end_time = getattr(process, 'end_time', None)
        if end_time:
            lines.append(f"Ended: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 计算持续时间
            duration = end_time - start_time
            duration_str = str(duration).split('.')[0]  # 移除微秒部分
            lines.append(f"Duration: {duration_str}")
        
        # 退出码
        exit_code = getattr(process, 'exit_code', None)
        if exit_code is not None:
            lines.append(f"Exit Code: {exit_code}")
        
        # 环境变量
        envs = getattr(process, 'envs', None)
        if envs and len(envs) > 0:
            lines.append("\n**Environment Variables:**")
            for key, value in envs.items():
                lines.append(f"- {key}={value}")
        
        # 输出信息
        lines.append("\n**Output Information:**")
        lines.append(f"To view standard output: `shell_bg_logs(process_id={pid})`")
        lines.append(f"To view error output: `shell_bg_logs(process_id={pid}, with_stderr=True)`")
        
        # 控制命令
        lines.append("\n**Control Commands:**")
        
        # 根据进程状态提供不同的命令
        if status == ProcessStatus.RUNNING or (isinstance(status, str) and status == 'running'):
            lines.append(f"Stop the process: `shell_bg_stop(process_id={pid})`")
            lines.append(f"Force stop the process: `shell_bg_stop(process_id={pid}, force=True)`")
        else:
            lines.append(f"Clean up the process: `shell_bg_clean(process_ids=[{pid}])`")
        
        return [TextContent(type="text", text="\n".join(lines))]
        
    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        logger.error(f"Error getting process details: {e}")
        raise ValueError(f"Error getting process details: {str(e)}")

def start_web_server(host: str = '0.0.0.0', port: Optional[int] = None, debug: bool = False, url_prefix: str = '') -> None:
    """在独立线程中启动Web服务器
    
    Args:
        host: 主机地址，默认为0.0.0.0
        port: 端口号，如果为None则使用随机端口
        debug: 是否开启调试模式
        url_prefix: URL前缀，用于在子路径下运行应用
    """
    global web_server_thread
    
    # 如果端口未指定，获取随机端口
    if port is None:
        port = get_free_port()
    
    def run_web_server():
        """在线程中运行Web服务器"""
        try:
            web_server.start_web_interface(host=host, port=port, debug=debug, prefix=url_prefix)
        except Exception as e:
            logger.error(f"Error starting Web interface: {e}", exc_info=True)
    
    # 创建并启动新线程
    web_server_thread = threading.Thread(target=run_web_server, daemon=True)
    web_server_thread.start()
    
    # 构建URL前缀字符串
    prefix_str = f"/{url_prefix.lstrip('/')}" if url_prefix else ""
    
    # 记录Web界面地址
    logger.info(f"Web management site start at {port}")
    
    # 如果绑定的是所有接口(0.0.0.0)，则显示localhost和实际的IP地址
    if host == '0.0.0.0':
        logger.info(f"you can access: http://localhost:{port}{prefix_str}")
        
        # 获取本机所有IP地址
        ip_addresses = get_local_ip_addresses()
        if ip_addresses:
            for ip in ip_addresses:
                logger.info(f"local access address: http://{ip}:{port}{prefix_str}")
    else:
        # 使用指定的主机地址
        logger.info(f"you can access: http://{host}:{port}{prefix_str}")

# Click命令组
@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="mcp-shell-server")
@click.pass_context
def cli(ctx):
    """MCP Shell Server - 用于执行shell命令的MCP协议服务器"""
    # 如果没有提供子命令，默认使用stdio模式
    if ctx.invoked_subcommand is None:
        ctx.invoke(stdio)

@cli.command()
@click.option("--web-host", default="0.0.0.0", help="Web服务器主机地址")
@click.option("--web-port", default=None, type=int, help="Web服务器端口，不指定则使用随机端口")
@click.option("--web-path", default="/web", help="Web服务器路径")
def stdio(web_host, web_port, web_path):    
    """使用stdio模式启动服务器（默认模式）"""
    logger.info(f"Starting MCP shell server (stdio mode) v{__version__}")
    
    # 启动Web服务器
    start_web_server(host=web_host, port=web_port, url_prefix=web_path)
    
    # 运行FastMCP服务器
    mcp.run(transport="stdio")

@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
@click.option("--web-path", default="/web", help="Web服务器路径，不指定则与SSE服务器共用同一端口")
def sse(host, port, web_path):
    """使用SSE模式启动服务器"""
    logger.info(f"Starting MCP shell server (SSE mode) v{__version__} on {host}:{port}")
    
    # 启动Web服务器，使用相同的主机和端口（如果未指定web_path）
    if web_path is None:
        web_host, web_port = host, port
        web_url_prefix = ''
    else:
        # 如果指定了不同的web_path，则使用默认主机和随机端口
        web_host, web_port = '0.0.0.0', None
        web_url_prefix = web_path.lstrip('/')
    
    start_web_server(host=web_host, port=web_port, url_prefix=web_url_prefix)
    
    # 设置FastMCP服务器配置，然后运行
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="sse")

@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
@click.option("--path", default="/mcp", help="服务器路径")
@click.option("--web-path", default="/web", help="Web服务器路径，不指定则与HTTP服务器共用同一端口")
def http(host, port, path, web_path):
    """使用streamable HTTP模式启动服务器"""
    logger.info(f"Starting MCP shell server (HTTP mode) v{__version__} on {host}:{port}{path}")
    
    # 启动Web服务器，使用相同的主机和端口（如果未指定web_path）
    if web_path is None:
        web_host, web_port = host, port
        web_url_prefix = ''
    else:
        # 如果指定了不同的web_path，则使用默认主机和随机端口
        web_host, web_port = '0.0.0.0', None
        web_url_prefix = web_path.lstrip('/')
    
    start_web_server(host=web_host, port=web_port, url_prefix=web_url_prefix)
    
    # 设置FastMCP服务器配置，然后运行
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.streamable_http_path = path
    mcp.run(transport="streamable-http")

def main() -> None:
    """Main entry point for the MCP shell server"""
    # 判断是否通过测试调用
    # 如果是以模块方式运行的测试 (python -m pytest)，则通过引用方式调用直接执行 run_stdio_server
    if "pytest" in sys.modules:
        # 测试环境下不执行CLI，避免与测试用例冲突
        return
    
    # 执行Click命令组 - 正常执行模式
    cli(standalone_mode=True)

if __name__ == "__main__":
    main()
