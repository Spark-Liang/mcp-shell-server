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
from typing import IO, Any, Dict, List, Optional, Union

from mcp_shell_server.command_preprocessor import CommandPreProcessor
from mcp_shell_server.command_validator import CommandValidator
from mcp_shell_server.directory_manager import DirectoryManager
from mcp_shell_server.io_redirection_handler import IORedirectionHandler
from mcp_shell_server.process_manager import ProcessManager


class ShellExecutor:
    """
    Executes shell commands in a secure manner by validating against a whitelist.
    """

    def __init__(self, process_manager: Optional[ProcessManager] = None):
        """
        Initialize the executor with a command validator, directory manager and IO handler.
        Args:
            process_manager: Optional ProcessManager instance for testing
        """
        self.validator = CommandValidator()
        self.directory_manager = DirectoryManager()
        self.io_handler = IORedirectionHandler()
        self.preprocessor = CommandPreProcessor()
        self.process_manager = (
            process_manager if process_manager is not None else ProcessManager()
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
            return os.environ.get("COMSPEC", "cmd.exe")
        else:
            # On Unix-like systems, try pwd, then SHELL env var, then default to /bin/sh
            if pwd: # Check if pwd was imported successfully
                try:
                    return pwd.getpwuid(os.getuid()).pw_shell
                except KeyError:
                    # Handle case where UID might not exist in pwd database
                    pass
            # Fallback for Unix-like systems
            return os.environ.get("SHELL", "/bin/sh")
            
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
        env_encoding = os.environ.get("DEFAULT_ENCODING")
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

    async def execute(
        self,
        command: List[str],
        directory: str,
        stdin: Optional[str] = None,
        timeout: Optional[int] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        process = None  # Initialize process variable
        
        # 如果未提供encoding，使用默认获取方法
        if encoding is None:
            encoding = self._get_default_encoding()

        try:
            # Validate directory if specified
            try:
                self._validate_directory(directory)
            except ValueError as e:
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

            # Process command
            preprocessed_command = self.preprocessor.preprocess_command(command)
            cleaned_command = self.preprocessor.clean_command(preprocessed_command)
            if not cleaned_command:
                return {
                    "error": "Empty command",
                    "status": 1,
                    "stdout": "",
                    "stderr": "Empty command",
                    "execution_time": time.time() - start_time,
                }

            # First check for pipe operators and handle pipeline
            if "|" in cleaned_command:
                try:
                    # Validate pipeline first using the validator
                    try:
                        self.validator.validate_pipeline(cleaned_command)
                    except ValueError as e:
                        return {
                            "error": str(e),
                            "status": 1,
                            "stdout": "",
                            "stderr": str(e),
                            "execution_time": time.time() - start_time,
                        }

                    # Split commands
                    commands = self.preprocessor.split_pipe_commands(cleaned_command)
                    if not commands:
                        raise ValueError("Empty command before pipe operator")

                    return await self._execute_pipeline(
                        commands, directory, timeout, envs, encoding
                    )
                except ValueError as e:
                    return {
                        "error": str(e),
                        "status": 1,
                        "stdout": "",
                        "stderr": str(e),
                        "execution_time": time.time() - start_time,
                    }

            # Then check for other shell operators
            for token in cleaned_command:
                try:
                    self.validator.validate_no_shell_operators(token)
                except ValueError as e:
                    return {
                        "error": str(e),
                        "status": 1,
                        "stdout": "",
                        "stderr": str(e),
                        "execution_time": time.time() - start_time,
                    }

            # Single command execution
            try:
                cmd, redirects = self.preprocessor.parse_command(cleaned_command)
            except ValueError as e:
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

            try:
                self.validator.validate_command(cmd)
            except ValueError as e:
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

            # Directory validation
            if directory:
                if not os.path.exists(directory):
                    return {
                        "error": f"Directory does not exist: {directory}",
                        "status": 1,
                        "stdout": "",
                        "stderr": f"Directory does not exist: {directory}",
                        "execution_time": time.time() - start_time,
                    }
                if not os.path.isdir(directory):
                    return {
                        "error": f"Not a directory: {directory}",
                        "status": 1,
                        "stdout": "",
                        "stderr": f"Not a directory: {directory}",
                        "execution_time": time.time() - start_time,
                    }
            if not cleaned_command:
                raise ValueError("Empty command")

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
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

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

            process = await self.process_manager.create_process(
                shell_cmd, directory, stdout_handle=stdout_handle, envs=envs
            )

            try:
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

                try:
                    # プロセス通信実行
                    stdout, stderr = await asyncio.shield(
                        self.process_manager.execute_with_timeout(
                            process, stdin=stdin, timeout=timeout
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
                        "execution_time": time.time() - start_time,
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

                    return {
                        "error": f"Command timed out after {timeout} seconds",
                        "status": -1,
                        "stdout": "",
                        "stderr": f"Command timed out after {timeout} seconds",
                        "execution_time": time.time() - start_time,
                    }

            except Exception as e:  # Exception handler for subprocess
                if isinstance(stdout_handle, IO):
                    stdout_handle.close()
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

        finally:
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
                    return {
                        "error": "Empty command in pipeline",
                        "status": 1,
                        "stdout": "",
                        "stderr": "Empty command in pipeline",
                        "execution_time": time.time() - start_time,
                    }
                self._validate_command(cmd)
        except ValueError as e:
            return {
                "error": str(e),
                "status": 1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": time.time() - start_time,
            }

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
                return {
                    "error": str(e),
                    "status": 1,
                    "stdout": current_input if current_input else "",
                    "stderr": str(e),
                    "execution_time": time.time() - start_time,
                }

        # Fallback return in case something went wrong or the pipeline was empty
        return {
            "error": "Pipeline executed but produced no output",
            "status": 1,
            "stdout": current_input if current_input else "",
            "stderr": "Pipeline executed but produced no output",
            "execution_time": time.time() - start_time,
        }
