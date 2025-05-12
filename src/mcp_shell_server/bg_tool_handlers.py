"""Tool handlers for background process management."""

import asyncio
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from mcp.types import TextContent
from pydantic import BaseModel, Field, field_validator, model_validator

from .interfaces import ToolHandler
from .backgroud_process_manager import (
    BackgroundProcessManager,
    ProcessStatus,
)

logger = logging.getLogger("mcp-shell-server")

# 全局后台进程管理器
background_process_manager = BackgroundProcessManager()


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
        from .shell_executor import ShellExecutor
        return f"Start a command **in background** and return its ID. Allowed commands: {', '.join(ShellExecutor().validator.get_allowed_commands())}"
        
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
            # 启动后台进程
            process_id = await background_process_manager.start_process(
                shell_cmd=command,
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
        status = arguments.status
        
        try:
            # 获取进程列表
            processes = await background_process_manager.list_processes(labels=labels, status=status)
            
            if not processes:
                return [TextContent(
                    type="text",
                    text="No background processes found"
                )]
                
            # 格式化输出
            lines = ["ID | STATUS | START TIME | COMMAND | DESCRIPTION | LABELS"]
            lines.append("-" * 100)
            
            for proc in processes:
                pid_short = proc["process_id"][:8]  # 使用ID的前8个字符
                cmd_str = " ".join(proc["command"])
                if len(cmd_str) > 30:
                    cmd_str = cmd_str[:27] + "..."
                    
                labels_str = ", ".join(proc["labels"]) if proc["labels"] else ""
                start_time = proc["start_time"].split("T")[0] + " " + proc["start_time"].split("T")[1][:8]
                
                lines.append(f"{pid_short} | {proc['status']} | {start_time} | {cmd_str} | {proc['description']} | {labels_str}")
                
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
        process_id = arguments.process_id
        force = arguments.force
        
        try:
            # 获取进程信息（用于返回消息）
            process = await background_process_manager.get_process(process_id)
            if not process:
                raise ValueError(f"Process with ID {process_id} not found")
                
            # 构建描述字符串
            cmd_str = " ".join(process.command)
            if len(cmd_str) > 30:
                cmd_str = cmd_str[:27] + "..."
                
            # 停止进程
            await background_process_manager.stop_process(process_id, force)
            
            return [TextContent(
                type="text",
                text=f"Process {process_id} has been {'forcefully terminated' if force else 'gracefully stopped'}\nCommand: {cmd_str}\nDescription: {process.description}"
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
        output: List[Dict[str, Any]], 
        stream_name: str, 
        add_time_prefix: bool, 
        time_prefix_format: str
    ) -> TextContent:
        """格式化进程输出"""
        if output:
            formatted_lines = []
            for line in output:
                if add_time_prefix:
                    timestamp = line["timestamp"].strftime(time_prefix_format)
                    formatted_lines.append(f"[{timestamp}] {line['text']}")
                else:
                    formatted_lines.append(line['text'])
            
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
            process = await background_process_manager.get_process(process_id)
            if not process:
                raise ValueError(f"Process with ID {process_id} not found")
                
            # 获取命令描述
            cmd_str = " ".join(process.command)
            if len(cmd_str) > 50:
                cmd_str = cmd_str[:47] + "..."
            
            # 添加进程信息作为第一个TextContent
            status_info = f"**Process {process_id[:8]} (status: {process.status})**\n"
            status_info += f"Command: {cmd_str}\n"
            status_info += f"Description: {process.description}"
            
            # 添加状态信息
            if process.status == ProcessStatus.RUNNING:
                status_info += "\nStatus: Process is still running"
            elif process.status == ProcessStatus.COMPLETED:
                status_info += f"\nStatus: Process completed successfully with exit code {process.exit_code}"
            else:
                status_info += f"\nStatus: Process {process.status} with exit code {process.exit_code}"
                
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
                if process.status == ProcessStatus.RUNNING:
                    await asyncio.sleep(follow_seconds)
            
            # 如果需要查看标准输出
            if with_stdout:
                # 获取标准输出
                stdout_output = await background_process_manager.get_process_output(
                    process_id=process_id,
                    tail=tail,
                    since_time=since.isoformat() if since else None,
                    until_time=until.isoformat() if until else None,
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
                stderr_output = await background_process_manager.get_process_output(
                    process_id=process_id,
                    tail=tail,
                    since_time=since.isoformat() if since else None,
                    until_time=until.isoformat() if until else None,
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
        process_ids = arguments.process_ids
        
        # 结果表格
        results = []
        
        for proc_id in process_ids:
            try:
                await background_process_manager.clean_completed_process(proc_id)
                results.append({
                    "process_id": proc_id,
                    "status": "SUCCESS",
                    "message": "Process cleaned successfully"
                })
            except ValueError as e:
                results.append({
                    "process_id": proc_id,
                    "status": "FAILED",
                    "message": str(e)
                })
            except Exception as e:
                logger.error(f"Error cleaning process {proc_id}: {e}")
                results.append({
                    "process_id": proc_id,
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
        process_id = arguments.process_id
        
        try:
            # 获取进程详情
            process = await background_process_manager.get_process(process_id)
            if not process:
                raise ValueError(f"Process with ID {process_id} not found")
                
            # 获取进程信息
            process_info = process.get_info()
            
            # 格式化输出
            lines = [f"### Process Details: {process_id}"]
            lines.append("")
            
            # 基本信息
            lines.append("#### Basic Information")
            lines.append(f"- **Status**: {process_info['status']}")
            lines.append(f"- **Command**: `{' '.join(process_info['command'])}`")
            lines.append(f"- **Description**: {process_info['description']}")
            if process_info['labels']:
                lines.append(f"- **Labels**: {', '.join(process_info['labels'])}")
            
            # 时间信息
            lines.append("")
            lines.append("#### Timing")
            start_time = process_info['start_time'].replace('T', ' ').split('.')[0]
            lines.append(f"- **Started**: {start_time}")
            
            if process_info['end_time']:
                end_time = process_info['end_time'].replace('T', ' ').split('.')[0]
                lines.append(f"- **Ended**: {end_time}")
                
                # 计算运行时间
                start_dt = datetime.fromisoformat(process_info['start_time'])
                end_dt = datetime.fromisoformat(process_info['end_time'])
                duration = end_dt - start_dt
                lines.append(f"- **Duration**: {duration}")
            
            # 执行信息
            lines.append("")
            lines.append("#### Execution")
            lines.append(f"- **Working Directory**: {process_info['directory']}")
            if process_info['exit_code'] is not None:
                lines.append(f"- **Exit Code**: {process_info['exit_code']}")
            
            # 进程输出信息
            lines.append("")
            lines.append("#### Output Information")
            lines.append(f"- Use `shell_bg_logs` tool to view process output")
            lines.append(f"- Example: `shell_bg_logs(process_id='{process_id}')`")
            
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