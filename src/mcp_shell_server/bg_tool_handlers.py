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
            process_id = await default_shell_executor.async_execute(
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
                text=f"Started background process with ID: {process_id}"
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
    process_id: str = Field(
        description="ID of the process to stop",
    )
    force: Optional[bool] = Field(
        default=False,
        description="Whether to force stop the process",
    )


class CleanProcessArgs(BaseModel):
    """清理进程的参数模型"""
    process_ids: List[str] = Field(
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
        pid = arguments.process_id
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
    process_id: str = Field(
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
        process_id = arguments.process_id
        tail = arguments.tail
        since = arguments.since
        until = arguments.until
        with_stdout = arguments.with_stdout
        with_stderr = arguments.with_stderr
        add_time_prefix = arguments.add_time_prefix
        time_prefix_format = arguments.time_prefix_format
        follow_seconds = arguments.follow_seconds
        
        content: List[TextContent] = []
        
        try:
            # 获取进程对象
            process = await default_shell_executor.get_process(process_id)
            if not process:
                raise ValueError(f"Process with ID {process_id} not found")
                
            # 获取进程信息
            process_info = None
            if hasattr(process, 'process_info'):
                process_info = process.process_info
            else:
                # 假设 process 是 BackgroundProcess 对象
                process_info_dict = {}
                for key in ['status', 'command', 'description', 'labels', 'start_time', 'end_time', 'exit_code']:
                    if hasattr(process, key):
                        process_info_dict[key] = getattr(process, key)
                process_info = process_info_dict
                
            # 获取命令描述
            cmd_str = process_info.shell_cmd if hasattr(process_info, 'shell_cmd') else process_info.get('command', '')
            if isinstance(cmd_str, list):
                cmd_str = ' '.join(cmd_str)
            if len(cmd_str) > 50:
                cmd_str = cmd_str[:47] + "..."
            
            # 获取状态
            status = process_info.status if hasattr(process_info, 'status') else process_info.get('status', 'unknown')
            if isinstance(status, ProcessStatus):
                status_value = status.value
            else:
                status_value = str(status)
                
            # 添加进程信息作为第一个TextContent
            status_info = f"**Process {process_id[:8]} (status: {status_value})**\n"
            status_info += f"Command: {cmd_str}\n"
            
            # 获取描述
            description = process_info.description if hasattr(process_info, 'description') else process_info.get('description', 'No description')
            status_info += f"Description: {description}"
            
            # 添加状态信息
            if status == ProcessStatus.RUNNING or status_value == 'running':
                status_info += "\nStatus: Process is still running"
            elif status == ProcessStatus.COMPLETED or status_value == 'completed':
                exit_code = process_info.exit_code if hasattr(process_info, 'exit_code') else process_info.get('exit_code')
                status_info += f"\nStatus: Process completed successfully with exit code {exit_code}"
            else:
                exit_code = process_info.exit_code if hasattr(process_info, 'exit_code') else process_info.get('exit_code')
                status_info += f"\nStatus: Process {status_value} with exit code {exit_code}"
                
            content.append(TextContent(type="text", text=status_info))
            
            # 验证至少选择了一种输出类型
            if not with_stdout and not with_stderr:
                content.append(TextContent(
                    type="text",
                    text="---\nNo output requested. Set with_stdout=true or with_stderr=true to view logs.\n---"
                ))
                return content
            
            # 如果设置了follow_seconds，添加提示信息
            if follow_seconds is not None and follow_seconds > 0:
                follow_info = f"\n正在等待进程输出... ({follow_seconds}秒)"
                content.append(TextContent(type="text", text=follow_info))
                
                # 等待指定秒数
                if status == ProcessStatus.RUNNING or status_value == 'running':
                    await asyncio.sleep(follow_seconds)
            
            # 如果需要查看标准输出
            if with_stdout:
                # 使用 ShellExecutor 获取标准输出
                stdout_output = await default_shell_executor.get_process_output(
                    process_id=process_id,
                    tail=tail,
                    since=since,
                    until=until,
                    error=False
                )
                
                content.append(self._format_process_output(
                    stdout_output, 
                    "stdout", 
                    add_time_prefix, 
                    time_prefix_format
                ))
                
            # 如果需要查看错误输出
            if with_stderr:
                # 使用 ShellExecutor 获取错误输出
                stderr_output = await default_shell_executor.get_process_output(
                    process_id=process_id,
                    tail=tail,
                    since=since,
                    until=until,
                    error=True
                )
                
                content.append(self._format_process_output(
                    stderr_output, 
                    "stderr", 
                    add_time_prefix, 
                    time_prefix_format
                ))
            
                
            return content
                
        except ValueError as e:
            raise ValueError(str(e))
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
        pids = arguments.process_ids
        
        # 结果表格
        results = []
        
        for pid in pids:
            try:
                # 获取进程状态
                process = await default_shell_executor.get_process(pid)
                if not process:
                    results.append({
                        "process_id": pid,
                        "status": "FAILED",
                        "message": "Process not found"
                    })
                    continue
                
                # 检查进程是否运行中
                status = None
                if hasattr(process, 'process_info'):
                    status = process.process_info.status
                elif hasattr(process, 'status'):
                    status = process.status
                    
                if status == ProcessStatus.RUNNING or status == 'running':
                    results.append({
                        "process_id": pid,
                        "status": "FAILED",
                        "message": "Process is still running, cannot clean"
                    })
                    continue
                
                # 使用 default_shell_executor 清理进程
                await default_shell_executor.clean_completed_process(pid)
                results.append({
                    "process_id": pid,
                    "status": "SUCCESS",
                    "message": "Process cleaned successfully"
                })
            except ValueError as e:
                results.append({
                    "process_id": pid,
                    "status": "FAILED",
                    "message": str(e)
                })
            except Exception as e:
                logger.error(f"Error cleaning process {pid}: {e}")
                results.append({
                    "process_id": pid,
                    "status": "ERROR",
                    "message": f"Unexpected error: {str(e)}"
                })
        
        # 格式化输出
        lines = ["PROCESS ID | STATUS | MESSAGE"]
        lines.append("-" * 100)
        
        for result in results:
            pid = result["process_id"]
            status = result["status"]
            message = result["message"]
            lines.append(f"{pid} | {status} | {message}")
            
        return [TextContent(
            type="text",
            text="\n".join(lines)
        )]


class GetProcessDetailArgs(BaseModel):
    """获取进程详情的参数模型"""
    process_id: str = Field(
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
        pid = arguments.process_id
        
        try:
            # 使用 ShellExecutor 获取进程详情
            process = await default_shell_executor.get_process(pid)
            if not process:
                raise ValueError(f"Process with ID {pid} not found")
                
            # 获取进程信息
            process_info = None
            if hasattr(process, 'process_info'):
                process_info = process.process_info
            elif hasattr(process, 'get_info'):
                process_info = process.get_info()
            else:
                # 假设 process 是 BackgroundProcess 对象
                process_info_dict = {}
                for key in ['command', 'directory', 'description', 'labels', 
                           'status', 'start_time', 'end_time', 'exit_code']:
                    if hasattr(process, key):
                        process_info_dict[key] = getattr(process, key)
                process_info = process_info_dict
                
            # 格式化输出
            lines = [f"### Process Details: {pid}"]
            lines.append("")
            
            # 基本信息
            lines.append("#### Basic Information")
            
            # 获取状态
            status = None
            if hasattr(process_info, 'status'):
                status = process_info.status
            else:
                status = process_info.get('status', 'unknown')
                
            if isinstance(status, ProcessStatus):
                status_value = status.value
            else:
                status_value = str(status)
                
            lines.append(f"- **Status**: {status_value}")
            
            # 获取命令
            command = None
            if hasattr(process_info, 'shell_cmd'):
                command = process_info.shell_cmd
            else:
                command = process_info.get('command', '')
                
            if isinstance(command, list):
                command = ' '.join(command)
                
            lines.append(f"- **Command**: `{command}`")
            
            # 获取描述
            description = None
            if hasattr(process_info, 'description'):
                description = process_info.description
            else:
                description = process_info.get('description', 'No description')
                
            lines.append(f"- **Description**: {description}")
            
            # 获取标签
            labels = None
            if hasattr(process_info, 'labels'):
                labels = process_info.labels
            else:
                labels = process_info.get('labels', [])
                
            if labels:
                lines.append(f"- **Labels**: {', '.join(labels)}")
            
            # 时间信息
            lines.append("")
            lines.append("#### Timing")
            
            # 获取开始时间
            start_time = None
            if hasattr(process_info, 'start_time'):
                start_time = process_info.start_time
            else:
                start_time = process_info.get('start_time')
                
            if isinstance(start_time, str):
                start_time_str = start_time.replace('T', ' ').split('.')[0]
            elif isinstance(start_time, datetime):
                start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            else:
                start_time_str = "Unknown"
                
            lines.append(f"- **Started**: {start_time_str}")
            
            # 获取结束时间
            end_time = None
            if hasattr(process_info, 'end_time'):
                end_time = process_info.end_time
            else:
                end_time = process_info.get('end_time')
                
            if end_time:
                if isinstance(end_time, str):
                    end_time_str = end_time.replace('T', ' ').split('.')[0]
                elif isinstance(end_time, datetime):
                    end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    end_time_str = "Unknown"
                    
                lines.append(f"- **Ended**: {end_time_str}")
                
                # 计算运行时间
                try:
                    if isinstance(start_time, str) and isinstance(end_time, str):
                        start_dt = datetime.fromisoformat(start_time)
                        end_dt = datetime.fromisoformat(end_time)
                        duration = end_dt - start_dt
                    elif isinstance(start_time, datetime) and isinstance(end_time, datetime):
                        duration = end_time - start_time
                    else:
                        duration = "Unknown"
                    lines.append(f"- **Duration**: {duration}")
                except Exception:
                    lines.append(f"- **Duration**: Unable to calculate")
            
            # 执行信息
            lines.append("")
            lines.append("#### Execution")
            
            # 获取工作目录
            directory = None
            if hasattr(process_info, 'directory'):
                directory = process_info.directory
            else:
                directory = process_info.get('directory', 'Unknown')
                
            lines.append(f"- **Working Directory**: {directory}")
            
            # 获取退出码
            exit_code = None
            if hasattr(process_info, 'exit_code'):
                exit_code = process_info.exit_code
            else:
                exit_code = process_info.get('exit_code')
                
            if exit_code is not None:
                lines.append(f"- **Exit Code**: {exit_code}")
            
            # 进程输出信息
            lines.append("")
            lines.append("#### Output Information")
            lines.append(f"- Use `shell_bg_logs` tool to view process output")
            lines.append(f"- Example: `shell_bg_logs(process_id='{pid}')`")
            
            return [TextContent(
                type="text",
                text="\n".join(lines)
            )]
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