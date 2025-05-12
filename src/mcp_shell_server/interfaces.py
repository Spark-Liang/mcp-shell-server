"""Tool handler abstraction for MCP shell server."""

import json
from typing import Any, Dict, List, Optional, Sequence, Type, Union, Generic, TypeVar, Protocol, Tuple, IO, AsyncGenerator
from abc import ABC, abstractmethod
from itertools import chain

from pydantic import BaseModel, ValidationError, Field
from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource
import pydantic_core

import asyncio.subprocess
from datetime import datetime
from enum import Enum

T_ARGUMENTS = TypeVar('T_ARGUMENTS', bound=BaseModel)

class ToolHandler(Generic[T_ARGUMENTS], ABC):
    """抽象基类，定义工具处理器接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    @abstractmethod
    def argument_model(self) -> Type[T_ARGUMENTS]:
        """参数模型类型"""
        pass
    
    def get_tool_def(self) -> Tool:
        """
        获取工具定义
        
        基于name、description和argument_model属性生成Tool对象
        
        Returns:
            Tool对象
        """
        # 从模型中提取JSON Schema
        schema = self.argument_model.model_json_schema()
        
        # 确保schema是一个有效的JSON Schema对象
        if not isinstance(schema, dict):
            raise ValueError("Model schema must be a dictionary")
        
        # 转换为Tool的inputSchema格式
        input_schema = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=input_schema,
        )

    def _convert_to_content(
        self, result: Any
    ) -> Sequence[Union[TextContent, ImageContent, EmbeddedResource]]:
        """
        将任意类型的结果转换为内容对象序列
        
        Args:
            result: 任意类型的结果
            
        Returns:
            内容对象序列
        """
        if result is None:
            return []

        if isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
            return [result]

        if isinstance(result, (list, tuple)):
            return list(chain.from_iterable(self._convert_to_content(item) for item in result))

        if not isinstance(result, str):
            try:
                result = json.dumps(pydantic_core.to_jsonable_python(result))
            except Exception:
                result = str(result)

        return [TextContent(type="text", text=result)]

    async def run_tool(
        self, arguments: dict
    ) -> Sequence[Union[TextContent, ImageContent, EmbeddedResource]]:
        """
        处理工具调用
        
        Args:
            arguments: 工具参数字典
            
        Returns:
            内容对象序列
        """
        try:
            # 验证并转换参数
            validated_args = self.argument_model.model_validate(arguments)
            # 调用具体实现
            result = await self._do_run_tool(validated_args)
            # 确保返回的是适当的内容对象序列
            return self._convert_to_content(result)
        except ValidationError as e:
            # 转换为ValueError以保持与原始代码一致的异常类型
            raise ValueError(str(e))
    
    @abstractmethod
    async def _do_run_tool(self, arguments: T_ARGUMENTS) -> Any:
        """
        实际执行工具的抽象方法
        
        Args:
            arguments: 已验证的参数对象
            
        Returns:
            工具执行结果，可以是任何类型
        """
        pass


# 进程状态枚举
class ProcessStatus(str, Enum):
    """进程状态枚举"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"
    ERROR = "error"

class ProcessInfo(BaseModel):
    """进程信息"""
    shell_cmd: str = Field(description="进程命令")
    directory: str = Field(description="进程工作目录")
    envs: Optional[Dict[str, str]] = Field(description="进程环境变量")
    timeout: Optional[int] = Field(description="进程超时时间，单位为秒")
    encoding: str = Field(description="进程输入输出字符集编码")
    description: str = Field(description="进程描述")
    labels: Optional[List[str]] = Field(description="进程标签")
    start_time: datetime = Field(description="进程开始时间")
    end_time: Optional[datetime] = Field(description="进程结束时间")
    status: ProcessStatus = Field(description="进程状态")
    exit_code: Optional[int] = Field(description="进程退出码")

class ExtendedProcess(Protocol):
    """扩展的Process协议，包含标准Process方法和扩展方法"""

    @property
    def returncode(self) -> Optional[int]:
        """进程返回码"""
        ...
        
    @property
    def pid(self) -> Optional[int]:
        """进程ID"""
        ...
        
    @property
    def stdin(self) -> Optional[asyncio.StreamWriter]:
        """标准输入流"""
        ...
        
    @property
    def stdout(self) -> Optional[asyncio.StreamReader]:
        """标准输出流"""
        ...
        
    @property
    def stderr(self) -> Optional[asyncio.StreamReader]:
        """标准错误流"""
        ...
        
    async def wait(self) -> int:
        """等待进程结束"""
        ...
        
    async def communicate(self, input: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        """与进程通信"""
        ...
        
    def terminate(self) -> None:
        """终止进程"""
        ...
        
    def kill(self) -> None:
        """强制终止进程"""
        ...

    @property
    def process_info(self) -> ProcessInfo:
        """进程信息"""
        ...

class IProcessManager(Protocol):

    @abstractmethod
    async def start_process(
        self, cmd: List[str], timeout: Optional[int] = None
    ) -> asyncio.subprocess.Process:
        """Start a new process asynchronously.

        Args:
            cmd: Command to execute as list of strings
            timeout: Optional timeout in seconds

        Returns:
            Process object
        """
        ...

    @abstractmethod
    async def cleanup_processes(
        self, processes: List[asyncio.subprocess.Process]
    ) -> None:
        """Clean up processes by killing them if they're still running.

        Args:
            processes: List of processes to clean up
        """
        ...
    
    @abstractmethod
    async def cleanup_all(self) -> None:
        """Clean up all tracked processes."""
        ...

    @abstractmethod
    async def create_process(
        self,
        shell_cmd: str,
        directory: Optional[str],
        stdin: Optional[str] = None,
        stdout_handle: Any = asyncio.subprocess.PIPE,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
        description: Optional[str] = "Default process description",
        labels: Optional[List[str]] = None
    ) -> Union[asyncio.subprocess.Process, ExtendedProcess]:
        """Create a new subprocess with the given parameters.

        Args:
            shell_cmd (str): Shell command to execute
            directory (Optional[str]): Working directory
            stdin (Optional[str]): Input to be passed to the process
            stdout_handle: File handle or PIPE for stdout
            envs (Optional[Dict[str, str]]): Additional environment variables
            encoding (Optional[str]): input output encoding
            timeout (Optional[int]): Timeout in seconds
            description (Optional[str]): Process description
            labels (Optional[List[str]]): Labels for categorizing the process

        Returns:
            Union[asyncio.subprocess.Process, ExtendedProcess]: Created process

        Raises:
            ValueError: If process creation fails
        """
        ...

    @abstractmethod
    async def execute_with_timeout(
        self,
        process: asyncio.subprocess.Process,
        stdin: Optional[bytes] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[bytes, bytes]:
        """Execute the process with timeout handling.

        Args:
            process: Process to execute
            stdin (Optional[bytes]): Input to pass to the process as bytes
            timeout (Optional[int]): Timeout in seconds

        Returns:
            Tuple[bytes, bytes]: Tuple of (stdout, stderr)

        Raises:
            asyncio.TimeoutError: If execution times out
        """
        ...

    @abstractmethod
    async def execute_pipeline(
        self,
        commands: List[str],
        first_stdin: Optional[bytes] = None,
        last_stdout: Union[IO[Any], int, None] = None,
        directory: Optional[str] = None,
        timeout: Optional[int] = None,
        envs: Optional[Dict[str, str]] = None,
    ) -> Tuple[bytes, bytes, int]:
        """Execute a pipeline of commands.

        Args:
            commands: List of shell commands to execute in pipeline
            first_stdin: Input to pass to the first command
            last_stdout: Output handle for the last command
            directory: Working directory
            timeout: Timeout in seconds
            envs: Additional environment variables

        Returns:
            Tuple[bytes, bytes, int]: Tuple of (stdout, stderr, return_code)

        Raises:
            ValueError: If no commands provided or command execution fails
        """
        ...

    async def list_processes(self, labels: Optional[List[str]] = None, status: Optional[ProcessStatus] = None) -> List[Dict[str, Any]]:
        """列出进程，可按标签和状态过滤。
        
        Args:
            labels: 标签过滤条件
            status: 状态过滤条件
            
        Returns:
            List[Dict]: 进程信息列表
        
        Raises:
             NotImplemented: 没有对应实现
        """
        raise NotImplemented()
    
    async def get_process(self, process_id: str) -> Optional[Union[asyncio.subprocess.Process, ExtendedProcess]]:
        """获取指定ID的进程对象。
        
        Args:
            process_id: 进程ID
            
        Returns:
            Optional[Union[asyncio.subprocess.Process, ExtendedProcess]]: 进程对象，如果不存在则返回None
        
        Raises:
             NotImplemented: 没有对应实现
        """
        raise NotImplemented()
        
    async def stop_process(self, process_id: str, force: bool = False) -> bool:
        """停止指定的进程。
        
        Args:
            process_id: 进程ID
            force: 是否强制停止
            
        Returns:
            bool: 是否成功停止
            
        Raises:
            ValueError: 进程不存在时抛出
            NotImplemented: 没有对应实现
        """
        raise NotImplemented()
    
    async def get_process_output(
        self,
        process_id: str,
        tail: Optional[int] = None,
        since_time: Optional[str] = None,
        until_time: Optional[str] = None,
        error: bool = False,
    ) -> List[Dict[str, Any]]:
        """获取进程的输出。
        
        Args:
            process_id: 进程ID
            tail: 只显示最后N行
            since_time: 只显示某个时间点之后的日志
            until_time: 只显示某个时间点之前的日志
            error: 是否获取错误输出
            
        Returns:
            List[Dict[str, Any]]: 输出行列表
            
        Raises:
            ValueError: 进程不存在时抛出
            NotImplemented: 没有对应实现
        """
        raise NotImplemented()
    
    async def get_all_output(
        self,
        process_id: str,
        tail: Optional[int] = None,
        since_time: Optional[str] = None,
        until_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取进程的所有输出（标准输出和错误输出合并）
        
        Args:
            process_id: 进程ID
            tail: 只返回最后N行，如果为None则返回所有行
            since_time: ISO格式的时间字符串，只返回该时间之后的日志
            until_time: ISO格式的时间字符串，只返回该时间之前的日志
            
        Returns:
            包含时间戳、文本和流类型的字典列表
        
        Raises:
            ValueError: 如果进程不存在
            NotImplemented: 没有对应实现
        """
        raise NotImplemented()
    
    async def follow_process_output(
        self,
        process_id: str,
        tail: Optional[int] = None,
        since_time: Optional[str] = None,
        error: bool = False,
        poll_interval: float = 0.5
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """以流式方式获取进程输出，适用于实时监控日志
        
        Args:
            process_id: 进程ID
            tail: 初始时获取最后N行，如果为None则获取所有行
            since_time: ISO格式的时间字符串，只返回该时间之后的日志
            error: 是否获取错误输出
            poll_interval: 轮询间隔，单位秒
            
        Yields:
            包含时间戳和文本的字典
            
        Raises:
            ValueError: 如果进程不存在
            NotImplemented: 没有对应实现
        """
        raise NotImplemented()