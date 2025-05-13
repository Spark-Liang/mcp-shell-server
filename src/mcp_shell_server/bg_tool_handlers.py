"""Tool handlers for background process management."""

import asyncio
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from mcp.types import TextContent
from pydantic import BaseModel, Field, field_validator, model_validator

from .interfaces import ToolHandler, LogEntry
from .background_process_manager import (
    ProcessStatus,
)
from .shell_executor import default_shell_executor

logger = logging.getLogger("mcp-shell-server")

# Pydantic 参数模型
class StartProcessArgs(BaseModel):
    """启动后台进程的参数模型"""
    command: List[str] = Field(
        description="Command and its arguments as array",
    )
    directory: str = Field(
        description="Absolute path to the working directory where the command will be executed",
    )
    description: str = Field(
        description="Description of the command (required)",
    )
    labels: Optional[List[str]] = Field(
        default=None,
        description="Labels to categorize the command",
    )
    stdin: Optional[str] = Field(
        default=None,
        description="Input to be passed to the command via stdin",
    )
    envs: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional environment variables for the command",
    )
    encoding: Optional[str] = Field(
        default=None,
        description="Character encoding for command output (e.g. 'utf-8', 'gbk', 'cp936')",
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Maximum execution time in seconds",
        ge=0,  # greater than or equal to 0
    )

    @field_validator('command')
    def command_not_empty(cls, v):
        if not v:
            raise ValueError("Command cannot be empty")
        return v

    @field_validator('directory')
    def directory_exists(cls, v):
        if not os.path.isdir(v):
            raise ValueError(f"Directory '{v}' does not exist")
        return v

class StartBackgroundProcessToolHandler(ToolHandler[StartProcessArgs]):
    """启动后台进程的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_start"
        
    @property
    def description(self) -> str:
        return f"Start a command **in background** and return its ID. Allowed commands: {', '.join(default_shell_executor.validator.get_allowed_commands())}"
        
    @property
    def argument_model(self) -> Type[StartProcessArgs]:
        return StartProcessArgs
        
    async def _do_run_tool(self, arguments: StartProcessArgs) -> Sequence[TextContent]:
        command = arguments.command
        directory = arguments.directory
        description = arguments.description  # 必填参数
        labels = arguments.labels
        stdin = arguments.stdin
        envs = arguments.envs
        encoding = arguments.encoding
        timeout = arguments.timeout
        
        try:
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


class ListProcessesArgs(BaseModel):
    """列出进程的参数模型"""
    labels: Optional[List[str]] = Field(
        default=None,
        description="Filter processes by labels",
    )
    status: Optional[str] = Field(
        default=None,
        description="Filter processes by status ('running', 'completed', 'failed', 'terminated', 'error')",
    )

    @field_validator('status')
    def validate_status(cls, v):
        if v and v not in [status.value for status in ProcessStatus]:
            raise ValueError(f"Status must be one of: {', '.join([status.value for status in ProcessStatus])}")
        return v

class ListBackgroundProcessesToolHandler(ToolHandler[ListProcessesArgs]):
    """列出后台进程的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_list"
        
    @property
    def description(self) -> str:
        return "List background processes with optional label and status filtering"
        
    @property
    def argument_model(self) -> Type[ListProcessesArgs]:
        return ListProcessesArgs
        
    async def _do_run_tool(self, arguments: ListProcessesArgs) -> Sequence[TextContent]:
        labels = arguments.labels
        status_str = arguments.status
        
        try:
            # 将状态字符串转换为枚举类型
            status = ProcessStatus(status_str) if status_str else None
            
            # 使用 ShellExecutor 获取进程列表
            processes = await default_shell_executor.list_processes(labels=labels, status=status)
            
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


class StopProcessArgs(BaseModel):
    """停止进程的参数模型"""
    pid: int = Field(
        description="ID of the process to stop",
    )
    force: Optional[bool] = Field(
        default=False,
        description="Whether to force stop the process",
    )


class CleanProcessArgs(BaseModel):
    """清理进程的参数模型"""
    pids: List[int] = Field(
        description="要清理的进程ID列表",
    )


class StopBackgroundProcessToolHandler(ToolHandler[StopProcessArgs]):
    """停止后台进程的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_stop"
        
    @property
    def description(self) -> str:
        return "Stop a background process"
        
    @property
    def argument_model(self) -> Type[StopProcessArgs]:
        return StopProcessArgs
        
    async def _do_run_tool(self, arguments: StopProcessArgs) -> Sequence[TextContent]:
        pid = arguments.pid
        force = arguments.force
        
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


class GetProcessOutputArgs(BaseModel):
    """获取进程输出的参数模型"""
    pid: int = Field(
        description="ID of the process to get output from",
    )
    tail: Optional[int] = Field(
        default=None,
        description="Number of lines to show from the end",
        gt=0,  # greater than 0
    )
    since: Optional[datetime] = Field(
        default=None,
        description="Show logs since timestamp (e.g. '2021-01-01T00:00:00')",
    )
    until: Optional[datetime] = Field(
        default=None,
        description="Show logs until timestamp (e.g. '2021-01-01T00:00:00')",
    )
    with_stdout: bool = Field(
        default=True,
        description="Show standard output",
    )
    with_stderr: bool = Field(
        default=False,
        description="Show error output",
    )
    add_time_prefix: bool = Field(
        default=True,
        description="Add timestamp prefix to each output line",
    )
    time_prefix_format: str = Field(
        default="%Y-%m-%d %H:%M:%S.%f",
        description="Format of the timestamp prefix, using strftime format",
    )
    follow_seconds: Optional[int] = Field(
        default=None,
        description="Wait for the specified number of seconds to get new logs. If None, return immediately.",
        ge=0,  # greater than or equal to 0
    )
    
    # 模型验证，处理从JSON序列化时字符串到datetime的转换
    @model_validator(mode='before')
    @classmethod
    def validate_timestamps(cls, values):
        if isinstance(values, dict):
            # 处理since字段
            if 'since' in values and values['since'] and isinstance(values['since'], str):
                try:
                    values['since'] = datetime.fromisoformat(values['since'])
                except ValueError:
                    raise ValueError("'since' must be a valid ISO format datetime string (e.g. '2021-01-01T00:00:00')")
                    
            # 处理until字段
            if 'until' in values and values['until'] and isinstance(values['until'], str):
                try:
                    values['until'] = datetime.fromisoformat(values['until'])
                except ValueError:
                    raise ValueError("'until' must be a valid ISO format datetime string (e.g. '2021-01-01T00:00:00')")
        return values

class GetBackgroundProcessOutputToolHandler(ToolHandler[GetProcessOutputArgs]):
    """获取后台进程输出的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_logs"
        
    @property
    def description(self) -> str:
        return "Get output from a background process, similar to 'docker logs'"
        
    @property
    def argument_model(self) -> Type[GetProcessOutputArgs]:
        return GetProcessOutputArgs
    
    def _format_process_output(
        self, 
        output: List[LogEntry], 
        stream_name: str, 
        add_time_prefix: bool, 
        time_prefix_format: str
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
            
            line_count = len(formatted_lines)
            output_text = "\n".join(formatted_lines)
            return TextContent(
                type="text", 
                text=f"---\n{stream_name}: {line_count} lines\n---\n{output_text}\n"
            )
        else:
            return TextContent(
                type="text",
                text=f"---\n{stream_name}: 0 lines\n---\n"
            )
        
    async def _do_run_tool(self, arguments: GetProcessOutputArgs) -> Sequence[TextContent]:
        pid = arguments.pid
        tail = arguments.tail
        since = arguments.since
        until = arguments.until
        with_stdout = arguments.with_stdout
        with_stderr = arguments.with_stderr
        add_time_prefix = arguments.add_time_prefix
        time_prefix_format = arguments.time_prefix_format
        follow_seconds = arguments.follow_seconds
        
        result_content: List[TextContent] = []
        
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
                
            result_content.append(TextContent(type="text", text=status_info))
            
            # 如果请求了标准输出
            if with_stdout:
                # 使用 ShellExecutor 获取标准输出
                stdout_output = await default_shell_executor.get_process_output(
                    pid=pid,
                    tail=tail,
                    since=since,
                    until=until,
                    error=False
                )
                
                if stdout_output:
                    # 格式化输出
                    stdout_content = self._format_process_output(
                        stdout_output, 
                        "STDOUT", 
                        add_time_prefix,
                        time_prefix_format
                    )
                    result_content.append(stdout_content)
                else:
                    result_content.append(TextContent(
                        type="text", 
                        text="No standard output available"
                    ))
            
            # 如果请求了错误输出
            if with_stderr:
                # 使用 ShellExecutor 获取错误输出
                stderr_output = await default_shell_executor.get_process_output(
                    pid=pid,
                    tail=tail,
                    since=since,
                    until=until,
                    error=True
                )
                
                if stderr_output:
                    # 格式化输出
                    stderr_content = self._format_process_output(
                        stderr_output, 
                        "STDERR", 
                        add_time_prefix,
                        time_prefix_format
                    )
                    result_content.append(stderr_content)
                else:
                    result_content.append(TextContent(
                        type="text", 
                        text="No error output available"
                    ))
                    
            # 如果指定了follow_seconds，显示帮助信息
            if follow_seconds is not None:
                help_lines = [
                    "\n---",
                    "**To continue following output:**",
                    "- For standard output: `shell_bg_logs(pid={}, follow_seconds=60)`".format(pid),
                ]
                if with_stderr:
                    help_lines.append("- For error output: `shell_bg_logs(pid={}, with_stderr=True, follow_seconds=60)`".format(pid))
                
                result_content.append(TextContent(
                    type="text",
                    text="\n".join(help_lines)
                ))
                
            return result_content
        except Exception as e:
            logger.error(f"Error getting process output: {e}")
            raise ValueError(f"Error getting process output: {str(e)}")


class CleanBackgroundProcessToolHandler(ToolHandler[CleanProcessArgs]):
    """清理后台进程的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_clean"
        
    @property
    def description(self) -> str:
        return "Clean background processes that have completed or failed"
        
    @property
    def argument_model(self) -> Type[CleanProcessArgs]:
        return CleanProcessArgs
        
    async def _do_run_tool(self, arguments: CleanProcessArgs) -> Sequence[TextContent]:
        pids = arguments.pids
        
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


class GetProcessDetailArgs(BaseModel):
    """获取进程详情的参数模型"""
    pid: int = Field(
        description="ID of the process to get details for",
    )


class GetBackgroundProcessDetailToolHandler(ToolHandler[GetProcessDetailArgs]):
    """获取后台进程详情的工具处理器"""
    
    @property
    def name(self) -> str:
        return "shell_bg_detail"
        
    @property
    def description(self) -> str:
        return "Get detailed information about a specific background process"
        
    @property
    def argument_model(self) -> Type[GetProcessDetailArgs]:
        return GetProcessDetailArgs
        
    async def _do_run_tool(self, arguments: GetProcessDetailArgs) -> Sequence[TextContent]:
        pid = arguments.pid
        
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
            lines.append("To view standard output: `shell_bg_logs(pid={})`".format(pid))
            lines.append("To view error output: `shell_bg_logs(pid={}, with_stderr=True)`".format(pid))
            
            # 控制命令
            lines.append("\n**Control Commands:**")
            
            # 根据进程状态提供不同的命令
            if status == ProcessStatus.RUNNING or (isinstance(status, str) and status == 'running'):
                lines.append("Stop the process: `shell_bg_stop(pid={})`".format(pid))
                lines.append("Force stop the process: `shell_bg_stop(pid={}, force=True)`".format(pid))
            else:
                lines.append("Clean up the process: `shell_bg_clean(pids=[{}])`".format(pid))
            
            return [TextContent(type="text", text="\n".join(lines))]
            
        except ValueError as e:
            raise ValueError(str(e))
        except Exception as e:
            logger.error(f"Error getting process details: {e}")
            raise ValueError(f"Error getting process details: {str(e)}")


# 列表，包含所有工具处理器
bg_tool_handlers = [
    StartBackgroundProcessToolHandler(),
    ListBackgroundProcessesToolHandler(),
    StopBackgroundProcessToolHandler(),
    GetBackgroundProcessOutputToolHandler(),
    CleanBackgroundProcessToolHandler(),
    GetBackgroundProcessDetailToolHandler(),
] 