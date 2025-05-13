import asyncio
import logging
import os
import sys  # Import sys module
import locale  # 导入locale模块获取系统编码
try:
    import pwd
except ImportError:
    pwd = None # Define pwd as None if import fails
import shlex
import time
from typing import IO, Any, Dict, List, Optional, Union, Iterable, Set
from datetime import datetime
from pydantic import BaseModel, Field

from .command_preprocessor import CommandPreProcessor
from .command_validator import CommandValidator
from .directory_manager import DirectoryManager
from .io_redirection_handler import IORedirectionHandler
from .background_process_manager import BackgroundProcessManager
from .interfaces import IProcessManager, ProcessInfo, ExtendedProcess, LogEntry, ProcessStatus
from .env_name_const import COMSPEC, SHELL, DEFAULT_ENCODING


class ShellCommandResponse(BaseModel):
    """Response model for shell command execution."""
    error: Optional[str] = Field(None, description="Error message if any")
    status: int = Field(..., description="Command exit code (0=success, non-zero=error, -1=timeout)")
    stdout: str = Field("", description="Standard output from the command")
    stderr: str = Field("", description="Standard error output from the command")
    execution_time: float = Field(..., description="Time taken to execute the command in seconds")
    directory: Optional[str] = Field(None, description="Directory where the command was executed")
    returncode: Optional[int] = Field(None, description="Return code of the command")
    
    def __getitem__(self, key: str) -> Any:
        """Support dictionary-like access."""
        return getattr(self, key)
    
    def __iter__(self) -> Iterable[str]:
        """Support iteration over keys."""
        return iter(self.model_fields.keys())
    
    def __contains__(self, key: str) -> bool:
        """Support 'in' operator."""
        return key in self.model_fields
    
    def keys(self) -> Set[str]:
        """Return all keys like a dictionary."""
        return set(self.model_fields.keys())
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value with a default, like a dictionary."""
        return getattr(self, key, default)


class ShellExecutionError(Exception):
    """Base class for shell execution errors."""
    
    def __init__(self, message: str, status: int = 1):
        """
        Initialize with error message and status code.
        
        Args:
            message: Error message
            status: Status code (default: 1, indicating error)
        """
        self.message = message
        self.status = status
        super().__init__(message)
    
    def to_response(self, start_time: float) -> ShellCommandResponse:
        """
        Convert exception to ShellCommandResponse.
        
        Args:
            start_time: The time when command execution started
            
        Returns:
            ShellCommandResponse object with error details
        """
        return ShellCommandResponse(
            error=self.message,
            status=self.status,
            stdout="",
            stderr=self.message,
            execution_time=time.time() - start_time
        )


class DirectoryError(ShellExecutionError):
    """Error raised when directory validation fails."""
    
    def __init__(self, message: str):
        """Initialize directory error with appropriate message."""
        super().__init__(message, status=1)


class CommandValidationError(ShellExecutionError):
    """Error raised when command validation fails."""
    
    def __init__(self, message: str):
        """Initialize command validation error with appropriate message."""
        super().__init__(message, status=1)


class EmptyCommandError(ShellExecutionError):
    """Error raised when command is empty."""
    
    def __init__(self, message: str = "Empty command"):
        """Initialize empty command error with default or custom message."""
        super().__init__(message, status=1)


class CommandTimeoutError(ShellExecutionError):
    """Error raised when command execution times out."""
    
    def __init__(self, message: str, timeout: Optional[int] = None):
        """
        Initialize timeout error with timeout information.
        
        Args:
            message: Error message
            timeout: The timeout value in seconds
        """
        self.timeout = timeout
        error_msg = message
        if timeout is not None:
            error_msg = f"Command timed out after {timeout} seconds"
        super().__init__(error_msg, status=-1)


class IORedirectionError(ShellExecutionError):
    """Error raised during IO redirection setup or handling."""
    
    def __init__(self, message: str):
        """Initialize IO redirection error with appropriate message."""
        super().__init__(message, status=1)


class ShellExecutor:
    """
    Executes shell commands in a secure manner by validating against a whitelist.
    """

    def __init__(self, process_manager: Optional[IProcessManager] = None):
        """
        Initialize the executor with a command validator, directory manager and IO handler.
        Args:
            process_manager: Optional IProcessManager instance for testing
        """
        self.validator = CommandValidator()
        self.directory_manager = DirectoryManager()
        self.io_handler = IORedirectionHandler()
        self.preprocessor = CommandPreProcessor()
        self.process_manager = (
            process_manager if process_manager is not None else BackgroundProcessManager()
        )

    def _validate_command(self, command: List[str]) -> None:
        """
        Validate if the command is allowed to be executed.

        Args:
            command (List[str]): Command and its arguments

        Raises:
            ValueError: If the command is empty, not allowed, or contains invalid shell operators
        """
        if not command:
            raise ValueError("Empty command")

        self.validator.validate_command(command)

    def _validate_directory(self, directory: Optional[str]) -> None:
        """
        Validate if the directory exists and is accessible.

        Args:
            directory (Optional[str]): Directory path to validate

        Raises:
            ValueError: If the directory doesn't exist, not absolute or is not accessible
        """
        self.directory_manager.validate_directory(directory)

    def _validate_no_shell_operators(self, cmd: str) -> None:
        """Validate that the command does not contain shell operators"""
        self.validator.validate_no_shell_operators(cmd)

    def _validate_pipeline(self, commands: List[str]) -> Dict[str, str]:
        """Validate pipeline command and ensure all parts are allowed

        Returns:
            Dict[str, str]: Error message if validation fails, empty dict if success
        """
        return self.validator.validate_pipeline(commands)

    def _get_default_shell(self) -> str:
        """Get the login shell of the current user, considering the OS."""
        if sys.platform == "win32":
            # On Windows, use COMSPEC environment variable or default to cmd.exe
            return os.environ.get(COMSPEC, "cmd.exe")
        else:
            # On Unix-like systems, try pwd, then SHELL env var, then default to /bin/sh
            if pwd: # Check if pwd was imported successfully
                try:
                    return pwd.getpwuid(os.getuid()).pw_shell
                except KeyError:
                    # Handle case where UID might not exist in pwd database
                    pass
            # Fallback for Unix-like systems
            return os.environ.get(SHELL, "/bin/sh")
            
    def _get_default_encoding(self) -> str:
        """获取默认字符编码，按优先级查找配置
        
        优先顺序:
        1. DEFAULT_ENCODING 环境变量
        2. 当前终端/系统使用的字符集
        3. 默认的 utf-8
        
        Returns:
            str: 默认字符编码
        """
        # 1. 优先使用环境变量中配置的字符集
        env_encoding = os.environ.get(DEFAULT_ENCODING)
        if env_encoding:
            return env_encoding
            
        # 2. 尝试获取终端/标准输出的编码
        terminal_encoding = None
        try:
            if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding:
                terminal_encoding = sys.stdout.encoding
            # 如果无法从标准输出获取，则尝试获取系统偏好编码
            if not terminal_encoding:
                terminal_encoding = locale.getpreferredencoding(False)
        except (AttributeError, Exception):
            pass
            
        if terminal_encoding:
            return terminal_encoding
            
        # 3. 最后使用默认的 utf-8
        return "utf-8"

    async def _do_execute(
        self,
        command: List[str],
        directory: str,
        stdin: Optional[str] = None,
        timeout: Optional[int] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        start_time: float = None,
    ) -> Dict[str, Any]:
        """
        Core execution logic for shell commands, with error handling through exceptions.
        
        Args:
            command: Command and its arguments as a list
            directory: Directory where the command will be executed
            stdin: Input to be passed to the command
            timeout: Maximum time in seconds to wait for the command to complete
            envs: Environment variables for the command
            encoding: Character encoding for the command output
            start_time: Time when execution started (for calculating execution_time)
            
        Returns:
            Dictionary with command execution results
            
        Raises:
            DirectoryError: If directory validation fails
            EmptyCommandError: If command is empty
            CommandValidationError: If command validation fails
            CommandTimeoutError: If command execution times out
            IORedirectionError: If IO redirection setup fails
            ShellExecutionError: For other execution errors
        """
        process = None
        
        # 如果未提供encoding，使用默认获取方法
        if encoding is None:
            encoding = self._get_default_encoding()
            
        # Validate directory if specified
        try:
            self._validate_directory(directory)
        except ValueError as e:
            raise DirectoryError(str(e))

        # Process command
        preprocessed_command = self.preprocessor.preprocess_command(command)
        cleaned_command = self.preprocessor.clean_command(preprocessed_command)
        if not cleaned_command:
            raise EmptyCommandError("Empty command")

        # First check for pipe operators and handle pipeline
        if "|" in cleaned_command:
            # Validate pipeline first using the validator
            try:
                self.validator.validate_pipeline(cleaned_command)
            except ValueError as e:
                raise CommandValidationError(str(e))

            # Split commands
            commands = self.preprocessor.split_pipe_commands(cleaned_command)
            if not commands:
                raise EmptyCommandError("Empty command before pipe operator")

            return await self._execute_pipeline(
                commands, directory, timeout, envs, encoding
            )

        # Then check for other shell operators
        for token in cleaned_command:
            try:
                self.validator.validate_no_shell_operators(token)
            except ValueError as e:
                raise CommandValidationError(str(e))

        # Single command execution
        try:
            cmd, redirects = self.preprocessor.parse_command(cleaned_command)
        except ValueError as e:
            raise IORedirectionError(str(e))

        try:
            self.validator.validate_command(cmd)
        except ValueError as e:
            raise CommandValidationError(str(e))

        # Directory validation
        if directory:
            if not os.path.exists(directory):
                raise DirectoryError(f"Directory does not exist: {directory}")
            if not os.path.isdir(directory):
                raise DirectoryError(f"Not a directory: {directory}")
                
        if not cleaned_command:
            raise EmptyCommandError("Empty command")

        # Initialize stdout_handle with default value
        stdout_handle: Union[IO[Any], int] = asyncio.subprocess.PIPE

        try:
            # Process redirections
            cmd, redirects = self.io_handler.process_redirections(cleaned_command)

            # Setup handles for redirection
            handles = await self.io_handler.setup_redirects(redirects, directory)

            # Get stdin and stdout from handles if present
            stdin_data = handles.get("stdin_data")
            if isinstance(stdin_data, str):
                stdin = stdin_data

            # Get stdout handle if present
            stdout_value = handles.get("stdout")
            if isinstance(stdout_value, (IO, int)):
                stdout_handle = stdout_value

        except ValueError as e:
            raise IORedirectionError(str(e))

        # Execute the command with interactive shell
        shell = self._get_default_shell()
        shell_cmd = self.preprocessor.create_shell_command(cmd)
        # Adjust shell execution command based on OS
        if sys.platform == "win32":
             # For cmd.exe, /c executes the command and then terminates
             shell_cmd = f'{shell} /c "{shell_cmd}"'
        else:
             # For sh/bash, -i for interactive, -c for command string
             shell_cmd = f"{shell} -i -c {shlex.quote(shell_cmd)}"

        try:
            process = await self.process_manager.create_process(
                shell_cmd, directory, stdout_handle=stdout_handle, envs=envs
            )

            # Send input if provided
            stdin_bytes = stdin.encode() if stdin else None

            async def communicate_with_timeout():
                try:
                    return await process.communicate(input=stdin_bytes)
                except Exception as e:
                    try:
                        await process.wait()
                    except Exception:
                        pass
                    raise e

            # プロセス通信実行
            stdout, stderr = await asyncio.shield(
                self.process_manager.execute_with_timeout(
                    process, stdin=stdin_bytes, timeout=timeout
                )
            )

            # ファイルハンドル処理
            if isinstance(stdout_handle, IO):
                try:
                    stdout_handle.close()
                except (IOError, OSError) as e:
                    logging.warning(f"Error closing stdout: {e}")

            # Handle case where returncode is None
            final_returncode = (
                0 if process.returncode is None else process.returncode
            )

            return {
                "error": None,
                "stdout": stdout.decode(encoding).strip() if stdout else "",
                "stderr": stderr.decode(encoding).strip() if stderr else "",
                "returncode": final_returncode,
                "status": process.returncode,
                "execution_time": time.time() - (start_time or time.time()),
                "directory": directory,
            }

        except asyncio.TimeoutError:
            # タイムアウト時のプロセスクリーンアップ
            if process and process.returncode is None:
                try:
                    process.kill()
                    await asyncio.shield(process.wait())
                except ProcessLookupError:
                    # Process already terminated
                    pass

            # ファイルハンドルクリーンアップ
            if isinstance(stdout_handle, IO):
                stdout_handle.close()

            raise CommandTimeoutError("Command timed out", timeout)

        except Exception as e:  # Exception handler for subprocess
            if isinstance(stdout_handle, IO):
                stdout_handle.close()
            raise ShellExecutionError(str(e))
        
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    async def execute(
        self,
        command: List[str],
        directory: str,
        stdin: Optional[str] = None,
        timeout: Optional[int] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
    ) -> ShellCommandResponse:
        """
        Execute a shell command synchronously and return the output.

        Args:
            command: List of command arguments
            directory: Directory where the command will be executed
            stdin: Input to be passed to the command
            timeout: Maximum time in seconds to wait for the command to complete
            envs: Environment variables for the command
            encoding: Character encoding for the command output
        
        Returns:
            ShellCommandResponse object with command execution results
        """
        start_time = time.time()
        process = None  # Initialize process variable
        
        try:
            # 调用_do_execute方法执行核心逻辑
            result_dict = await self._do_execute(
                command, directory, stdin, timeout, envs, encoding, start_time
            )
            return ShellCommandResponse.model_validate(result_dict)
        except ShellExecutionError as e:
            # 处理自定义异常
            return e.to_response(start_time)
        except asyncio.TimeoutError:
            # 处理异步超时
            error_msg = f"Command timed out after {timeout} seconds"
            return ShellCommandResponse(
                error=error_msg,
                status=-1,
                stdout="",
                stderr=error_msg,
                execution_time=time.time() - start_time,
            )
        except Exception as e:
            # 处理其他未预期的异常
            return ShellCommandResponse(
                error=str(e),
                status=1,
                stdout="",
                stderr=str(e),
                execution_time=time.time() - start_time,
            )
        finally:
            # 确保进程被清理
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    async def _execute_pipeline(
        self,
        commands: List[List[str]],
        directory: Optional[str] = None,
        timeout: Optional[int] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        current_input = None
        final_returncode = 0
        
        # 如果未提供encoding，使用默认获取方法
        if encoding is None:
            encoding = self._get_default_encoding()

        # Validate all commands first
        try:
            for cmd in commands:
                if not cmd:
                    raise EmptyCommandError("Empty command in pipeline")
                self._validate_command(cmd)
        except ValueError as e:
            raise CommandValidationError(str(e))

        # Process each command in the pipeline
        for i, cmd in enumerate(commands):
            # Last command in pipeline
            is_last = i == len(commands) - 1

            # Setup process
            try:
                shell = self._get_default_shell()
                shell_cmd = self.preprocessor.create_shell_command(cmd)

                process = await self.process_manager.create_process(
                    shell_cmd, shell, directory, envs
                )

                stdout, stderr = await process.communicate(
                    input=current_input.encode() if current_input else None
                )

                # Store output for next command
                current_input = stdout.decode(encoding) if stdout else ""
                if process.returncode != 0:
                    final_returncode = process.returncode

                # If this is the last command, collect stderr
                if is_last:
                    return {
                        "error": None,
                        "stdout": stdout.decode(encoding).strip() if stdout else "",
                        "stderr": stderr.decode(encoding).strip() if stderr else "",
                        "returncode": final_returncode,
                        "status": process.returncode,
                        "execution_time": time.time() - start_time,
                    }
            except Exception as e:
                raise ShellExecutionError(
                    str(e) if not isinstance(e, ShellExecutionError) else e.message
                )

        # Fallback - should not normally reach here
        raise ShellExecutionError("Pipeline executed but produced no output")


    async def async_execute(
        self, 
        command: List[str], 
        directory: str, 
        description: str = None,
        stdin: Optional[str] = None, 
        timeout: Optional[int] = None, 
        envs: Optional[Dict[str, str]] = None, 
        encoding: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> str:
        """
        Execute a shell command asynchronously and return the process ID.

        Args:
            command: List of command arguments
            directory: Directory where the command will be executed
            description: Description of the command
            stdin: Input to be passed to the command
            timeout: Maximum time in seconds to wait for the command to complete
            envs: Environment variables for the command
            encoding: Character encoding for the command output
            labels: Labels for the command

        Returns:
            Process ID of the started process
        """
        try:
            # 使用 preprocessor 预处理命令
            preprocessed_command = self.preprocessor.preprocess_command(command)
            cleaned_command = self.preprocessor.clean_command(preprocessed_command)
            
            # 验证命令和目录
            if not cleaned_command:
                raise ValueError("Empty command")
                
            self._validate_command(cleaned_command)
            self._validate_directory(directory)

            # 管道命令不支持
            for token in cleaned_command:
                self.validator.validate_no_shell_operators(token)
            
            # 如果未提供encoding，使用默认获取方法
            if encoding is None:
                encoding = self._get_default_encoding()
                
            # 创建命令字符串
            shell_cmd = self.preprocessor.create_shell_command(cleaned_command)
            
            # 调用进程管理器创建后台进程
            process_id = await self.process_manager.start_process(
                shell_cmd=shell_cmd,
                directory=directory,
                description=description or "Command execution",
                labels=labels,
                stdin=stdin,
                envs=envs,
                encoding=encoding,
                timeout=timeout
            )
            
            return process_id
            
        except Exception as e:
            # 处理异常
            raise ValueError(f"Failed to start background process: {str(e)}")
    
    async def list_processes(
        self, 
        labels: Optional[List[str]] = None, 
        status: Optional[ProcessStatus] = None
    ) -> List[ProcessInfo]:
        """
        List all processes, optionally filtered by labels and status.

        Args:
            labels: Optional list of labels to filter by
            status: Optional status to filter by

        Returns:
            List of ProcessInfo objects
        """
        return await self.process_manager.list_processes(labels=labels, status=status)

    async def get_process(self, pid: str = None, process_id: str = None) -> Optional[Union[asyncio.subprocess.Process, ExtendedProcess]]:
        """
        Get a process by its PID.
        
        Args:
            pid: Process ID (deprecated, use process_id instead)
            process_id: Process ID

        Returns:
            Process object, or None if not found
        """
        # 优先使用process_id
        actual_id = process_id if process_id is not None else pid
        return await self.process_manager.get_process(actual_id)

    async def stop_process(
        self, 
        pid: str = None, 
        process_id: str = None,
        force: bool = False
    ) -> bool:
        """
        Stop a process by its PID.
        
        Args:
            pid: Process ID (deprecated, use process_id instead)
            process_id: Process ID
            force: If True, forcefully stop the process

        Returns:
            True if process was stopped successfully

        Raises:
            ValueError: If process is not found
        """
        # 优先使用process_id
        actual_id = process_id if process_id is not None else pid
        return await self.process_manager.stop_process(actual_id, force=force)

    async def get_process_output(
        self, 
        pid: str = None, 
        process_id: str = None,
        tail: Optional[int] = None, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None, 
        error: bool = False
    ) -> List[LogEntry]:
        """
        Get the output of a process.

        Args:
            pid: Process ID (deprecated, use process_id instead)
            process_id: Process ID
            tail: Number of lines to return from the end of the output
            since: Return only output since this timestamp
            until: Return only output until this timestamp
            error: Whether to get stderr (True) or stdout (False)

        Returns:
            A list of LogEntry objects
        """
        # 优先使用process_id
        actual_id = process_id if process_id is not None else pid
        return await self.process_manager.get_process_output(
            pid=actual_id, 
            tail=tail,
            since_time=since.isoformat() if since else None,
            until_time=until.isoformat() if until else None,
            error=error
        )
        
    async def clean_completed_process(self, pid: str = None, process_id: str = None) -> None:
        """
        Clean up a completed process, removing it from the process manager.
        
        Args:
            pid: Process ID (deprecated, use process_id instead)
            process_id: Process ID to clean up
            
        Raises:
            ValueError: If the process is not found or is still running
        """
        # 优先使用process_id
        actual_id = process_id if process_id is not None else pid
        return await self.process_manager.clean_completed_process(actual_id)


# 创建全局默认实例供其他模块使用
default_shell_executor = ShellExecutor()
    
    
    
