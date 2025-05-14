"""后台进程管理模块，用于创建、执行和管理后台进程。"""

import asyncio
import logging
import os
import signal
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Any, Union, IO, Tuple, AsyncGenerator
from unittest.mock import MagicMock

from pydantic import BaseModel, Field, field_validator

from .interfaces import LogEntry, ProcessInfo, ProcessStatus, IProcessManager, ExtendedProcess
from .output_manager import OutputManager
from .env_name_const import PROCESS_RETENTION_SECONDS

logger = logging.getLogger("mcp-shell-server")

class BackgroundProcess(ExtendedProcess):
    """表示一个后台运行的进程"""
    def __init__(self, 
                shell_cmd: str, 
                directory: str,
                description: str,  # 描述是必填项
                labels: Optional[List[str]] = None,
                process: Optional[asyncio.subprocess.Process] = None,
                encoding: Optional[str] = None,
                timeout: Optional[int] = None,  # 添加超时参数
                envs: Optional[Dict[str, str]] = None):  # 添加环境变量
        """初始化后台进程对象
        
        Args:
            shell_cmd: 要执行的命令字符串
            directory: 工作目录
            description: 进程描述(必填)
            labels: 用于分类的标签列表
            process: asyncio子进程对象
            encoding: 输出字符编码
            timeout: 超时时间(秒)
            envs: 环境变量字典
        """
        # 生成临时ID，用于日志目录（在进程创建前pid可能为None）
        temp_id = str(uuid.uuid4())[:8]
        
        self.command = shell_cmd  # 命令字符串
        self.directory = directory  # 工作目录
        self.description = description  # 命令描述
        self.labels = labels or []  # 标签列表
        self.process = process  # 实际的进程对象
        self.encoding = encoding or 'utf-8'  # 字符编码，默认utf-8
        self.start_time = datetime.now()  # 启动时间
        self.timeout = timeout  # 超时时间(秒)
        self.envs = envs  # 环境变量
        
        # 创建临时目录用于存储日志文件
        self.log_dir = os.path.join(tempfile.gettempdir(), f"mcp_shell_logs_{temp_id}")
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 创建OutputManager实例
        self._output_manager = OutputManager()
        
        # 日志文件路径
        self.stdout_log = os.path.join(self.log_dir, "stdout.log")
        self.stderr_log = os.path.join(self.log_dir, "stderr.log")
        
        # 获取stdout和stderr的OutputLogger
        self._stdout_logger = self._output_manager.get_logger(self.stdout_log)
        self._stderr_logger = self._output_manager.get_logger(self.stderr_log)
        
        # 记录最后一次输出和错误输出的时间戳
        self.last_stdout_timestamp = None
        self.last_stderr_timestamp = None
        
        self.status = ProcessStatus.RUNNING  # 进程状态
        self.exit_code = None  # 退出码
        self.end_time = None  # 结束时间
        self.monitor_task = None  # 监控任务
        self.stdout_task = None  # 标准输出读取任务
        self.stderr_task = None  # 标准错误读取任务
        
        # 延迟清理相关属性
        self.cleanup_scheduled = False  # 是否已安排清理
        self.cleanup_handle = None  # 清理任务句柄

    @property
    def returncode(self) -> Optional[int]:
        """获取进程返回码，兼容 asyncio.subprocess.Process 接口。

        Returns:
            Optional[int]: 进程返回码，如果进程未结束则为 None
        """
        if self.process:
            return self.process.returncode
        return self.exit_code
    
    @property
    def pid(self) -> Optional[int]:
        """获取进程 PID，兼容 asyncio.subprocess.Process 接口。

        Returns:
            Optional[int]: 进程 PID，如果进程不存在则为 None
        """
        if self.process:
            return self.process.pid
        return None

    @pid.setter
    def pid(self, value: int) -> None:
        """设置进程PID，主要用于测试

        Args:
            value: 要设置的PID值
        """
        # 创建一个模拟进程对象
        if not self.process:
            self.process = MagicMock()
        self.process.pid = value

    @property
    def stdin(self) -> Optional[asyncio.StreamWriter]:
        """获取进程标准输入流，兼容 asyncio.subprocess.Process 接口。

        Returns:
            Optional[asyncio.StreamWriter]: 进程标准输入流，如果不存在则为 None
        """
        if self.process:
            return self.process.stdin
        return None
    
    @property
    def stdout(self) -> Optional[asyncio.StreamReader]:
        """获取进程标准输出流，兼容 asyncio.subprocess.Process 接口。

        Returns:
            Optional[asyncio.StreamReader]: 进程标准输出流，如果不存在则为 None
        """
        if self.process:
            return self.process.stdout
        return None
    
    @property
    def stderr(self) -> Optional[asyncio.StreamReader]:
        """获取进程标准错误流，兼容 asyncio.subprocess.Process 接口。

        Returns:
            Optional[asyncio.StreamReader]: 进程标准错误流，如果不存在则为 None
        """
        if self.process:
            return self.process.stderr
        return None

    @property
    def process_info(self) -> ProcessInfo:
        """获取进程基本信息
        
        Returns:
            ProcessInfo: 包含进程基本信息的字典
        """
        return ProcessInfo(
            pid=self.pid,
            shell_cmd=self.command,
            directory=self.directory,
            envs=self.envs,
            timeout=self.timeout,
            encoding=self.encoding,
            description=self.description,
            labels=self.labels,
            start_time=self.start_time,
            end_time=self.end_time,
            status=self.status,
            exit_code=self.exit_code
        )

    def __getattr__(self, name: str) -> Any:
        """转发未定义的属性和方法到内部 process 对象，提供兼容性。
        
        Args:
            name: 属性或方法名
            
        Returns:
            Any: 属性值或方法
            
        Raises:
            AttributeError: 如果属性或方法不存在
        """
        if self.process is not None:
            return getattr(self.process, name)
        raise AttributeError(f"'BackgroundProcess' object has no attribute '{name}' and internal process is None")

    async def wait(self) -> int:
        """等待进程结束，兼容 asyncio.subprocess.Process 接口。
        
        Returns:
            int: 进程退出码
            
        Raises:
            RuntimeError: 如果内部进程不存在且没有记录退出码
        """
        if self.process:
            return await self.process.wait()
        
        # 如果内部进程不存在但有退出码，直接返回
        if self.exit_code is not None:
            return self.exit_code
            
        # 如果进程不存在且没有退出码，可能是异常情况
        raise RuntimeError("等待进程结束失败: 内部进程不存在且没有退出码")
        
    async def communicate(self, input: Optional[bytes] = None, *, timeout: Optional[float] = None) -> Tuple[bytes, bytes]:
        """与进程通信并获取其输出，兼容 asyncio.subprocess.Process 接口。
        
        Args:
            input: 发送到进程的输入数据
            timeout: 通信的超时时间（秒）
            
        Returns:
            Tuple[bytes, bytes]: 包含标准输出和标准错误的元组
            
        Raises:
            RuntimeError: 如果内部进程不存在
            TimeoutError: 如果通信超时
        """
        if self.process:
            try:
                if timeout is not None:
                    # 使用 asyncio.wait_for 实现超时功能，不假设 process.communicate 支持 timeout
                    # 注意这里调用 communicate 时不传递 timeout 参数
                    try:
                        return await asyncio.wait_for(
                            self.process.communicate(input=input), 
                            timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        raise TimeoutError("进程通信超时")
                else:
                    # 无超时限制的情况
                    return await self.process.communicate(input=input)
            except Exception as e:
                # 如果不是超时错误，重新抛出
                if not isinstance(e, (TimeoutError, asyncio.TimeoutError)):
                    raise
                # 超时错误已经在上面处理过了，这里重新抛出
                raise
            
        # 如果内部进程不存在，尝试从日志中获取输出
        if self._stdout_logger and self._stderr_logger:
            stdout_logs = self._stdout_logger.get_logs()
            stderr_logs = self._stderr_logger.get_logs()
            
            # 将日志记录对象转换为字节字符串
            stdout_bytes = "\n".join([log.text for log in stdout_logs]).encode(self.encoding)
            stderr_bytes = "\n".join([log.text for log in stderr_logs]).encode(self.encoding)
            
            return stdout_bytes, stderr_bytes
            
        # 如果进程和日志都不存在，抛出异常
        raise RuntimeError("无法与进程通信: 内部进程不存在且无法获取日志")

    def terminate(self) -> None:
        """终止进程，兼容 asyncio.subprocess.Process 接口。
        
        Raises:
            RuntimeError: 如果内部进程不存在
        """
        if self.process:
            self.process.terminate()
            self.status = ProcessStatus.TERMINATED
            self.end_time = datetime.now()
            return
        
        # 如果内部进程不存在，设置状态并记录日志
        if self.status in [ProcessStatus.RUNNING, ProcessStatus.ERROR]:
            self.status = ProcessStatus.TERMINATED
            self.end_time = datetime.now()
            self.add_error("进程被请求终止，但内部进程对象不存在")
        else:
            # 如果进程已经不在运行状态，则忽略终止请求
            pass
    
    def kill(self) -> None:
        """强制终止进程，兼容 asyncio.subprocess.Process 接口。
        
        Raises:
            RuntimeError: 如果内部进程不存在
        """
        if self.process:
            self.process.kill()
            self.status = ProcessStatus.TERMINATED
            self.end_time = datetime.now()
            return
        
        # 如果内部进程不存在，设置状态并记录日志
        if self.status in [ProcessStatus.RUNNING, ProcessStatus.ERROR]:
            self.status = ProcessStatus.TERMINATED
            self.end_time = datetime.now()
            self.add_error("进程被请求强制终止，但内部进程对象不存在")
        else:
            # 如果进程已经不在运行状态，则忽略终止请求
            pass

    def get_info(self) -> Dict[str, Any]:
        """获取进程基本信息
        
        Returns:
            dict: 包含进程基本信息的字典
        """
        return {
            "pid": self.pid,
            "command": self.command,
            "directory": self.directory,
            "description": self.description,
            "labels": self.labels,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "exit_code": self.exit_code
        }
        
    def is_running(self) -> bool:
        """检查进程是否仍在运行
        
        Returns:
            bool: 进程是否运行中
        """
        if self.process and self.process.returncode is None:
            return True
        return self.status == ProcessStatus.RUNNING

    def add_output(self, line: str) -> None:
        """添加输出到标准输出日志
        
        Args:
            line: 输出行
        """
        timestamp = datetime.now()
        self.last_stdout_timestamp = timestamp
        
        # 使用OutputLogger添加日志
        self._stdout_logger.add_line(line)
    
    def add_error(self, line: str) -> None:
        """添加错误输出到错误日志
        
        Args:
            line: 错误输出行
        """
        timestamp = datetime.now()
        self.last_stderr_timestamp = timestamp
        
        # 使用OutputLogger添加日志
        self._stderr_logger.add_line(line)
    
    def get_output(self, tail: Optional[int] = None, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[LogEntry]:
        """获取标准输出
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的输出
            until: 只返回指定时间之前的输出
            
        Returns:
            输出列表，每条记录为LogEntry对象
        """
        # 使用OutputLogger获取日志
        return self._stdout_logger.get_logs(tail=tail, since=since, until=until)
    
    def get_error(self, tail: Optional[int] = None, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[LogEntry]:
        """获取错误输出
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的输出
            until: 只返回指定时间之前的输出
            
        Returns:
            错误输出列表，每条记录为LogEntry对象
        """
        # 使用OutputLogger获取日志
        return self._stderr_logger.get_logs(tail=tail, since=since, until=until)
            
    def cleanup(self) -> None:
        """清理进程资源，包括日志文件"""
        # 关闭OutputLogger
        self._output_manager.close_all()
        
        try:
            # 尝试移除日志目录
            if os.path.exists(self.log_dir):
                # 如果目录存在（某些日志可能没有被OutputLogger清理），则尝试移除
                if os.path.isdir(self.log_dir) and not any(os.scandir(self.log_dir)):
                    os.rmdir(self.log_dir)
        except Exception as e:
            logger.warning(f"清理日志目录时出错: {e}")


class BackgroundProcessManager(IProcessManager):
    """管理后台进程的创建、执行和清理。"""

    def __init__(self):
        """初始化BackgroundProcessManager，设置信号处理。"""
        # 使用字典存储进程，便于通过ID访问
        self._processes: Dict[str, BackgroundProcess] = {}
        self._original_sigint_handler = None
        self._original_sigterm_handler = None
        self._setup_signal_handlers()
        
        # 进程保留时间设置（秒）
        self._auto_cleanup_age = int(os.environ.get(PROCESS_RETENTION_SECONDS, 300))  # 默认5分钟

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器，用于优雅地管理进程。"""
        if os.name != "posix":
            return

        def handle_termination(signum: int, _: Any) -> None:
            """处理终止信号，清理进程。"""
            if self._processes:
                for pid, bg_process in list(self._processes.items()):
                    try:
                        if bg_process.process and bg_process.process.returncode is None:
                            bg_process.process.terminate()
                    except Exception as e:
                        logger.warning(
                            f"终止进程时出错 (信号 {signum}): {e}"
                        )

            # 恢复原始处理器并重新引发信号
            if signum == signal.SIGINT and self._original_sigint_handler:
                signal.signal(signal.SIGINT, self._original_sigint_handler)
            elif signum == signal.SIGTERM and self._original_sigterm_handler:
                signal.signal(signal.SIGTERM, self._original_sigterm_handler)

            # 重新引发信号
            os.kill(os.getpid(), signum)

        # 存储原始处理器
        self._original_sigint_handler = signal.signal(signal.SIGINT, handle_termination)
        self._original_sigterm_handler = signal.signal(
            signal.SIGTERM, handle_termination
        )
        
    async def execute_with_timeout(
        self,
        process: Union[asyncio.subprocess.Process, BackgroundProcess],
        stdin: Optional[bytes] = None,
        timeout: Optional[float] = None
    ) -> Tuple[bytes, bytes]:
        """执行进程并等待其完成，支持超时。兼容 ProcessManager.execute_with_timeout 接口。
        
        Args:
            process: 要执行的进程对象
            stdin: 要发送到进程的输入数据
            timeout: 执行的超时时间（秒）
            
        Returns:
            Tuple[bytes, bytes]: 包含标准输出和标准错误的元组
            
        Raises:
            TimeoutError: 如果执行超时
            RuntimeError: 如果进程执行出错
        """
        try:
            # 根据process的类型选择不同的处理方式
            if isinstance(process, BackgroundProcess):
                # 对于BackgroundProcess，使用特殊处理：等待进程完成后获取日志
                
                # 如果提供了输入，尝试写入
                if stdin and process.process and process.process.stdin:
                    try:
                        process.process.stdin.write(stdin)
                        await process.process.stdin.drain()
                        process.process.stdin.close()
                    except Exception as e:
                        logger.warning(f"写入进程输入时出错: {e}")
                
                # 等待进程完成
                try:
                    if timeout is not None:
                        await asyncio.wait_for(process.wait(), timeout=timeout)
                    else:
                        await process.wait()
                except asyncio.TimeoutError:
                    raise TimeoutError("进程执行超时")
                
                # 从日志获取输出
                stdout_logs = process.get_output()
                stderr_logs = process.get_error()
                
                # 将日志转换为字节字符串
                stdout_bytes = "\n".join([log.text for log in stdout_logs]).encode(process.encoding)
                stderr_bytes = "\n".join([log.text for log in stderr_logs]).encode(process.encoding)
                
                return stdout_bytes, stderr_bytes
            else:
                # 对于普通的asyncio.subprocess.Process，使用标准方法
                if timeout is not None:
                    try:
                        return await asyncio.wait_for(
                            process.communicate(input=stdin), 
                            timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        raise TimeoutError("进程执行超时")
                else:
                    return await process.communicate(input=stdin)
                    
        except (asyncio.TimeoutError, TimeoutError) as e:
            # 超时时，尝试终止进程
            try:
                process.terminate()
                # 等待进程响应终止信号
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    # 如果进程在给定时间内未终止，尝试强制终止
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=1.0)
            except Exception as term_err:
                logger.warning(f"终止超时进程时出错: {term_err}")
                
            # 重新抛出超时异常
            raise TimeoutError(f"进程执行超时: {str(e)}")
        
    async def _read_stream(self, stream: asyncio.StreamReader, is_error: bool, bg_process: BackgroundProcess) -> None:
        """持续读取流并存储到日志。
        
        Args:
            stream: 要读取的流
            is_error: 是否为错误流
            bg_process: 后台进程对象
        """
        try:
            # 缓存行以批量添加
            buffer = []
            buffer_size = 10  # 每次批量处理的行数
            buffer_timeout = 0.5  # 缓冲区超时时间（秒）
            last_flush_time = asyncio.get_event_loop().time()
            
            while True:
                line = await stream.readline()
                if not line:  # EOF
                    break
                    
                try:
                    decoded_line = line.decode(bg_process.encoding, errors='replace').rstrip()
                    buffer.append(decoded_line)
                    
                    # 达到缓冲区上限或超时时刷新
                    current_time = asyncio.get_event_loop().time()
                    if len(buffer) >= buffer_size or (current_time - last_flush_time) >= buffer_timeout:
                        if is_error:
                            # 批量添加错误输出
                            if callable(getattr(bg_process._stderr_logger, "add_lines", None)):
                                bg_process._stderr_logger.add_lines(buffer)
                            else:
                                # 如果无法批量添加，则单独添加每一行
                                for line in buffer:
                                    bg_process.add_error(line)
                        else:
                            # 批量添加标准输出
                            if callable(getattr(bg_process._stdout_logger, "add_lines", None)):
                                bg_process._stdout_logger.add_lines(buffer)
                            else:
                                # 如果无法批量添加，则单独添加每一行
                                for line in buffer:
                                    bg_process.add_output(line)
                        
                        # 清空缓冲区并更新最后刷新时间
                        buffer = []
                        last_flush_time = current_time
                        
                except UnicodeDecodeError as e:
                    logger.warning(f"解码进程输出时出错: {e}")
            
            # 处理缓冲区中剩余的行
            if buffer:
                if is_error:
                    # 批量添加错误输出
                    if callable(getattr(bg_process._stderr_logger, "add_lines", None)):
                        bg_process._stderr_logger.add_lines(buffer)
                    else:
                        for line in buffer:
                            bg_process.add_error(line)
                else:
                    # 批量添加标准输出
                    if callable(getattr(bg_process._stdout_logger, "add_lines", None)):
                        bg_process._stdout_logger.add_lines(buffer)
                    else:
                        for line in buffer:
                            bg_process.add_output(line)
                    
        except asyncio.CancelledError:
            # 任务被取消，确保缓冲区中的行被处理
            if buffer:
                try:
                    if is_error:
                        if callable(getattr(bg_process._stderr_logger, "add_lines", None)):
                            bg_process._stderr_logger.add_lines(buffer)
                        else:
                            for line in buffer:
                                bg_process.add_error(line)
                    else:
                        if callable(getattr(bg_process._stdout_logger, "add_lines", None)):
                            bg_process._stdout_logger.add_lines(buffer)
                        else:
                            for line in buffer:
                                bg_process.add_output(line)
                except Exception as e:
                    logger.error(f"处理剩余输出时出错: {e}")
            
            # 正常退出
            raise
            
        except Exception as e:
            logger.error(f"读取进程输出时出错: {e}")
            
    async def _monitor_process(self, bg_process: BackgroundProcess) -> None:
        """监控进程状态并管理输出流读取。
        
        Args:
            bg_process: 要监控的后台进程
        """
        try:
            # 启动输出流读取任务
            if bg_process.process and bg_process.process.stdout:
                bg_process.stdout_task = asyncio.create_task(
                    self._read_stream(bg_process.process.stdout, False, bg_process)
                )
                
            # 启动错误流读取任务
            if bg_process.process and bg_process.process.stderr:
                bg_process.stderr_task = asyncio.create_task(
                    self._read_stream(bg_process.process.stderr, True, bg_process)
                )
                
            # 等待进程结束，支持超时处理
            if bg_process.process:
                try:
                    if bg_process.timeout is not None:
                        # 使用超时等待进程结束
                        try:
                            exit_code = await asyncio.wait_for(
                                bg_process.process.wait(), 
                                timeout=bg_process.timeout
                            )
                            bg_process.exit_code = exit_code
                            bg_process.status = ProcessStatus.COMPLETED if exit_code == 0 else ProcessStatus.FAILED
                        except asyncio.TimeoutError:
                            # 超时发生，记录信息并终止进程
                            logger.warning(f"进程 {bg_process.pid} 执行超时 ({bg_process.timeout}秒)")
                            bg_process.add_error(f"进程执行超时，超过 {bg_process.timeout} 秒")
                            
                            # 尝试终止进程
                            try:
                                if asyncio.iscoroutinefunction(bg_process.process.terminate):
                                    await bg_process.process.terminate()
                                else:
                                    bg_process.process.terminate()
                                # 给进程一些时间来正常退出
                                try:
                                    await asyncio.wait_for(bg_process.process.wait(), timeout=2.0)
                                except asyncio.TimeoutError:
                                    # 如果仍然无法终止，强制结束
                                    if asyncio.iscoroutinefunction(bg_process.process.kill):
                                        await bg_process.process.kill()
                                    else:
                                        bg_process.process.kill()
                                    await asyncio.wait_for(bg_process.process.wait(), timeout=1.0)
                            except Exception as e:
                                logger.error(f"终止超时进程时出错: {e}")
                                
                            bg_process.status = ProcessStatus.TERMINATED
                            bg_process.exit_code = -1  # 使用-1表示超时终止
                    else:
                        # 无超时限制，正常等待进程结束
                        exit_code = await bg_process.process.wait()
                        bg_process.exit_code = exit_code
                        bg_process.status = ProcessStatus.COMPLETED if exit_code == 0 else ProcessStatus.FAILED
                    
                    bg_process.end_time = datetime.now()
                    
                    # 进程已终止，安排延迟清理
                    self.schedule_delayed_cleanup(bg_process.pid)
                finally:
                    # 等待输出流读取任务完成
                    tasks = []
                    if bg_process.stdout_task:
                        tasks.append(bg_process.stdout_task)
                    if bg_process.stderr_task:
                        tasks.append(bg_process.stderr_task)
                        
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    
        except asyncio.CancelledError:
            # 取消监控任务，终止进程
            if bg_process.process and bg_process.process.returncode is None:
                try:
                    bg_process.process.terminate()
                    await asyncio.wait_for(bg_process.process.wait(), timeout=2.0)
                except Exception as e:
                    logger.warning(f"终止进程时出错: {e}")
                    try:
                        bg_process.process.kill()
                    except Exception:
                        pass
                        
            # 取消流读取任务
            if bg_process.stdout_task and not bg_process.stdout_task.done():
                bg_process.stdout_task.cancel()
                
            if bg_process.stderr_task and not bg_process.stderr_task.done():
                bg_process.stderr_task.cancel()
                
            bg_process.status = ProcessStatus.TERMINATED
            bg_process.end_time = datetime.now()
            
            # 进程被取消，安排延迟清理
            self.schedule_delayed_cleanup(bg_process.pid)
            
        except Exception as e:
            logger.error(f"监控进程时出错: {e}")
            bg_process.status = ProcessStatus.ERROR
            bg_process.end_time = datetime.now()
            
            # 进程出错，安排延迟清理
            self.schedule_delayed_cleanup(bg_process.pid)
            
            # 确保进程已终止
            if bg_process.process and bg_process.process.returncode is None:
                try:
                    bg_process.process.kill()
                except Exception:
                    pass

    async def create_process(
        self,
        shell_cmd: str,
        directory: Optional[str],
        stdin: Optional[str] = None,
        stdout_handle: Any = asyncio.subprocess.PIPE,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
        description: str = "Default process description",
        labels: Optional[List[str]] = None,
    ) -> Union[asyncio.subprocess.Process, BackgroundProcess]:
        """创建一个新的后台进程。

        Args:
            shell_cmd: 要执行的命令字符串
            directory: 工作目录
            stdin: 传递给进程的输入
            stdout_handle: 标准输出处理（为兼容 ProcessManager，但在后台进程中不使用）
            envs: 额外的环境变量
            encoding: 输出编码
            timeout: 超时时间（秒）
            description: 进程描述
            labels: 进程标签列表

        Returns:
            Union[asyncio.subprocess.Process, BackgroundProcess]: 创建的后台进程对象

        Raises:
            ValueError: 如果进程创建失败
        """
        # 记录进程启动详细信息
        logger.info(f"start process:")
        logger.info(f"   command: {shell_cmd}")
        logger.info(f"   working directory: {directory}")
        if envs:
            logger.info(f"   environment variables: {envs}")
        logger.info(f"   description: {description}")
        if labels:
            logger.info(f"   labels: {labels}")
        if encoding:
            logger.info(f"   encoding: {encoding}")
        if timeout:
            logger.info(f"   timeout: {timeout} seconds")
        
        try:
            # 创建实际的子进程
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,  # 后台进程总是使用PIPE，忽略stdout_handle参数
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **(envs or {})},
                cwd=directory,
            )

            # 创建后台进程对象
            bg_process = BackgroundProcess(
                shell_cmd=shell_cmd,
                directory=directory or os.getcwd(),
                description=description,
                labels=labels,
                process=process,
                encoding=encoding,
                timeout=timeout,
                envs=envs,
            )
            
            # 获取进程pid
            pid = process.pid
            if pid is None:
                raise ValueError("进程创建成功但无法获取pid")
                
            # 将进程添加到管理的字典中，使用pid作为键
            self._processes[pid] = bg_process
            
            # 如果提供了stdin，发送到进程
            if stdin and process.stdin:
                try:
                    stdin_bytes = stdin.encode(bg_process.encoding)
                    await process.stdin.write(stdin_bytes)
                    await process.stdin.drain()
                    process.stdin.close()
                except Exception as e:
                    logger.warning(f"写入进程输入时出错: {e}")
            
            # 创建监控任务
            bg_process.monitor_task = asyncio.create_task(self._monitor_process(bg_process))
            
            return bg_process

        except OSError as e:
            raise ValueError(f"创建进程失败: {str(e)}") from e
        except Exception as e:
            raise ValueError(
                f"进程创建过程中出现意外错误: {str(e)}"
            ) from e
            
    async def start_process(
        self,
        shell_cmd: str,
        directory: str,
        description: str = "Default process description",  # 添加默认值
        labels: Optional[List[str]] = None,
        stdin: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> int:
        """启动一个后台进程并返回其PID。

        Args:
            shell_cmd: 要执行的命令字符串
            directory: 工作目录
            description: 命令描述(必填)
            labels: 标签列表
            stdin: 标准输入
            envs: 环境变量
            encoding: 字符编码
            timeout: 超时时间(秒)
            
        Returns:
            int: 进程PID
            
        Raises:
            ValueError: 如果进程创建失败
        """
        bg_process = await self.create_process(
            shell_cmd=shell_cmd,
            directory=directory,
            description=description,
            labels=labels,
            stdin=stdin,
            envs=envs,
            encoding=encoding,
            timeout=timeout,
        )
        
        # 确保我们得到的是 BackgroundProcess 对象
        if isinstance(bg_process, BackgroundProcess):
            if bg_process.pid is None:
                raise ValueError("进程创建成功但无法获取pid")
            return bg_process.pid
        else:
            # 这种情况不应该发生，但为了类型安全
            raise ValueError("内部错误：create_process 没有返回 BackgroundProcess 对象")
        
    async def list_processes(self, labels: Optional[List[str]] = None, status: Optional[ProcessStatus] = None) -> List[ProcessInfo]:
        """列出进程，可按标签和状态过滤。
        
        Args:
            labels: 标签过滤条件
            status: 状态过滤条件
            
        Returns:
            List[ProcessInfo]: 进程信息列表
        """
        result = []
        
        for pid, bg_process in self._processes.items():
            # 如果指定了标签过滤，检查是否匹配
            if labels and not any(label in labels for label in bg_process.labels):
                continue
                
            # 如果指定了状态过滤，检查是否匹配
            if status and bg_process.status != status:
                continue
                
            result.append(bg_process.process_info)
            
        return result
    
    async def get_process(self, pid: int) -> Optional[BackgroundProcess]:
        """获取指定PID的进程对象。
        
        Args:
            pid: 进程PID
            
        Returns:
            Optional[BackgroundProcess]: 进程对象，如果不存在则返回None
        """
        return self._processes.get(pid)
        
    async def stop_process(self, pid: int, force: bool = False) -> bool:
        """停止后台进程
        
        Args:
            pid: 进程PID
            force: 是否强制终止进程
            
        Returns:
            bool: 操作是否成功
            
        Raises:
            ValueError: 如果进程不存在
        """
        # 获取后台进程
        bg_process = await self.get_process(pid)
        if not bg_process:
            raise ValueError(f"没有找到PID为 {pid} 的进程")
            
        # 检查进程是否已经终止
        if not bg_process.is_running():
            logger.warning(f"进程 {pid} 已经终止")
            return True
            
        try:
            # 如果进程仍在运行，尝试终止它
            if force:
                # 强制终止
                bg_process.kill()
                logger.info(f"强制终止进程 {pid}")
            else:
                # 尝试优雅终止
                bg_process.terminate()
                logger.info(f"终止进程 {pid}")
                
            # 等待进程终止
            await asyncio.sleep(0.5)  # 给进程一点时间来终止
            
            # 更新状态
            if bg_process.is_running():
                # 如果进程仍在运行，并且我们使用了force=True，则再尝试一次强制终止
                if force:
                    logger.warning(f"进程 {pid} 没有响应终止信号，尝试强制终止")
                    bg_process.kill()
                    await asyncio.sleep(0.5)  # 再次等待
                
                # 最终检查
                if bg_process.is_running():
                    logger.error(f"无法终止进程 {pid}")
                    return False
            
            # 进程已终止，确保状态为TERMINATED
            bg_process.status = ProcessStatus.TERMINATED
            bg_process.end_time = datetime.now()
                    
            # 进程已终止
            logger.info(f"进程 {pid} 已终止")
            return True
            
        except Exception as e:
            logger.error(f"终止进程 {pid} 时出错: {e}")
            return False
    
    async def get_process_output(
        self,
        pid: int,
        tail: Optional[int] = None,
        since_time: Optional[datetime] = None,
        until_time: Optional[datetime] = None,
        error: bool = False,
    ) -> List[LogEntry]:
        """获取进程的输出日志
        
        Args:
            pid: 进程PID
            tail: 只返回最后n行
            since_time: 只返回此时间后的日志
            until_time: 只返回此时间前的日志
            error: 是否获取错误输出
            
        Returns:
            List[LogEntry]: 日志条目列表
            
        Raises:
            ValueError: 如果进程不存在或其他错误
        """
        bg_process = await self.get_process(pid)
        if not bg_process:
            raise ValueError(f"没有找到PID为 {pid} 的进程")
            
        # 获取输出
        try:
            if error:
                return bg_process.get_error(tail=tail, since=since_time, until=until_time)
            else:
                return bg_process.get_output(tail=tail, since=since_time, until=until_time)
        except Exception as e:
            raise ValueError(f"获取进程输出时出错: {str(e)}")
    
    async def follow_process_output(
        self,
        pid: int,
        tail: Optional[int] = None,
        since_time: Optional[datetime] = None,
        error: bool = False,
        poll_interval: float = 0.5
    ) -> AsyncGenerator[LogEntry, None]:
        """实时跟踪进程输出
        
        Args:
            pid: 进程PID
            tail: 首次获取的尾部行数
            since_time: 只返回此时间后的日志
            error: 是否获取错误输出
            poll_interval: 轮询间隔(秒)
            
        Yields:
            LogEntry: 日志条目
            
        Raises:
            ValueError: 如果进程不存在
        """
        bg_process = await self.get_process(pid)
        if not bg_process:
            raise ValueError(f"没有找到PID为 {pid} 的进程")
                
        # 首次获取现有日志
        logs = []
        if error:
            # 处理可能是协程的情况
            if asyncio.iscoroutinefunction(bg_process.get_error):
                logs = await bg_process.get_error(tail=tail, since=since_time)
            else:
                logs = bg_process.get_error(tail=tail, since=since_time)
        else:
            # 处理可能是协程的情况
            if asyncio.iscoroutinefunction(bg_process.get_output):
                logs = await bg_process.get_output(tail=tail, since=since_time)
            else:
                logs = bg_process.get_output(tail=tail, since=since_time)
                
        for log in logs:
            yield log
            
        # 记住最后一条日志的时间
        last_time = logs[-1].timestamp if logs else (since_time or datetime.now())
        
        # 持续轮询新日志
        while bg_process.is_running():
            await asyncio.sleep(poll_interval)
            
            # 获取自上次查询以来的新日志
            new_logs = []
            if error:
                # 处理可能是协程的情况
                if asyncio.iscoroutinefunction(bg_process.get_error):
                    new_logs = await bg_process.get_error(since=last_time)
                else:
                    new_logs = bg_process.get_error(since=last_time)
            else:
                # 处理可能是协程的情况
                if asyncio.iscoroutinefunction(bg_process.get_output):
                    new_logs = await bg_process.get_output(since=last_time)
                else:
                    new_logs = bg_process.get_output(since=last_time)
            
            if new_logs:
                last_time = new_logs[-1].timestamp
                for log in new_logs:
                    yield log
    
    async def cleanup_processes(self, processes: Optional[List[Union[asyncio.subprocess.Process, BackgroundProcess]]] = None, labels: Optional[List[str]] = None, status: Optional[ProcessStatus] = None) -> int:
        """清理进程，可接受进程列表或按标签和状态过滤。
        
        这个方法有两种调用方式：
        1. 传入进程列表: cleanup_processes([process1, process2, ...])
        2. 按标签或状态过滤: cleanup_processes(labels=["web"], status=ProcessStatus.COMPLETED)
        
        Args:
            processes: 要清理的进程列表（可选）
            labels: 标签过滤条件（可选）
            status: 状态过滤条件（可选）
            
        Returns:
            int: 清理的进程数量
            
        Note:
            当传入进程列表时，标签和状态过滤将被忽略。
        """
        # 处理直接传入进程列表的情况（用于与 ProcessManager 兼容）
        if processes is not None:
            count = 0
            for proc in processes:
                if isinstance(proc, BackgroundProcess):
                    # 对于 BackgroundProcess 对象，我们需要找到它在 self._processes 中的 ID
                    try:
                        # 检查进程是否正在运行
                        if proc.is_running():
                            proc_pid = proc.pid if hasattr(proc, 'pid') else None
                            if proc_pid and proc_pid in self._processes:
                                # 使用已有的方法停止进程
                                await self.stop_process(proc_pid, force=True)
                                count += 1
                            else:
                                # 直接终止进程
                                proc.kill()
                                try:
                                    await proc.wait()
                                except Exception as e:
                                    logger.warning(f"等待 BackgroundProcess 终止时出错: {e}")
                                count += 1
                    except ProcessLookupError:
                        # 进程可能已经不存在
                        logger.warning("尝试清理不存在的进程")
                    except Exception as e:
                        logger.error(f"清理 BackgroundProcess 时出错: {e}")
                else:
                    # 对于普通的 asyncio.subprocess.Process 对象
                    try:
                        if proc.returncode is None:
                            # 进程仍在运行，尝试终止
                            proc.kill()
                            try:
                                await proc.wait()
                            except Exception as e:
                                logger.warning(f"等待进程终止时出错: {e}")
                            count += 1
                    except ProcessLookupError:
                        # 进程可能已经不存在
                        logger.warning("尝试清理不存在的进程")
                    except Exception as e:
                        logger.error(f"清理进程时出错: {e}")
            return count
        
        # 按标签和状态过滤清理进程（原有行为）
        to_remove = []
        
        # 查找已完成的进程
        for pid, bg_process in self._processes.items():
            # 如果进程仍在运行，且未指定状态，跳过
            if bg_process.is_running() and not status:
                continue
                
            # 如果指定了状态过滤，检查是否匹配
            if status and bg_process.status != status:
                continue
                
            # 如果指定了标签过滤，检查是否匹配
            if labels and not any(label in labels for label in bg_process.labels):
                continue
                
            to_remove.append(pid)
            
        # 移除进程
        for pid in to_remove:
            await self.cleanup_process(pid)
            del self._processes[pid]
            
            
        return len(to_remove)

    async def cleanup_process(self, pid: int) -> None:
        """清理进程资源
        
        Args:
            pid: 进程PID
            
        Raises:
            ValueError: 如果进程不存在
        """
        # 获取后台进程
        bg_process = await self.get_process(pid)
        if not bg_process:
            raise ValueError(f"没有找到PID为 {pid} 的进程")
            
        # 如果进程仍在运行，先尝试终止它
        if bg_process.is_running():
            await self.stop_process(pid, force=True)
            await asyncio.sleep(0.5)  # 给进程一点时间来终止
            
        # 清理进程资源
        if bg_process.monitor_task and not bg_process.monitor_task.done():
            bg_process.monitor_task.cancel()
            
        if bg_process.stdout_task and not bg_process.stdout_task.done():
            bg_process.stdout_task.cancel()
            
        if bg_process.stderr_task and not bg_process.stderr_task.done():
            bg_process.stderr_task.cancel()
            
        # 调用进程自身的清理方法
        try:
            bg_process.cleanup()
        except Exception as e:
            logger.error(f"清理进程 {pid} 资源时出错: {e}")
            
        # 移除进程
        if pid in self._processes:
            del self._processes[pid]
        
    async def clean_completed_process(self, pid: int) -> bool:
        """清理已完成的进程，非运行中的进程
        
        Args:
            pid: 进程PID
            
        Returns:
            bool: 是否成功清理
        """
        # 获取后台进程
        bg_process = self._processes.get(pid)
        if not bg_process:
            logger.warning(f"尝试清理不存在的进程 {pid}")
            return False
            
        # 如果进程仍在运行，不清理
        if bg_process.is_running():
            logger.warning(f"进程 {pid} 仍在运行，不能清理")
            return False
            
        try:
            # 清理资源
            await self.cleanup_process(pid)
            logger.info(f"已清理已完成的进程 {pid}")
            return True
        except Exception as e:
            logger.error(f"清理已完成的进程 {pid} 时出错: {e}")
            return False

    async def cleanup_all(self) -> None:
        """清理所有进程，无论是否运行中"""
        # 获取所有进程的PID
        pids = list(self._processes.keys())
        
        # 清理每个进程
        cleanup_count = 0
        for pid in pids:
            try:
                await self.cleanup_process(pid)
                cleanup_count += 1
            except Exception as e:
                logger.error(f"清理进程 {pid} 时出错: {e}")
                
        logger.info(f"已清理 {cleanup_count} 个进程")

    async def execute_pipeline(
        self,
        commands: List[str],
        directory: str,
        description: str = "Default pipeline command",  # 添加默认值
        labels: Optional[List[str]] = None,
        first_stdin: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[bytes, bytes, int]:
        """执行管道命令序列，将多个命令的执行连接起来。
        
        按照顺序执行多个命令，每个命令的输出作为下一个命令的输入。
        
        Args:
            commands: 要执行的命令列表，每个命令作为一个字符串
            directory: 工作目录
            description: 管道命令描述
            labels: 命令标签列表
            first_stdin: 传递给第一个命令的输入
            envs: 额外的环境变量
            encoding: 输出编码
            timeout: 整个管道的超时时间(秒)
            
        Returns:
            Tuple[bytes, bytes, int]: (标准输出, 标准错误, 返回码)的元组
            
        Raises:
            ValueError: 如果命令列表为空或进程创建失败
            TimeoutError: 如果执行超时
        """
        if not commands:
            raise ValueError("No commands provided")
            
        # 将可能的文本输入转换为字节
        first_stdin_bytes = None
        if first_stdin is not None:
            first_stdin_bytes = first_stdin.encode(encoding or 'utf-8')
            
        processes = []
        final_stderr = b""
        
        try:
            prev_stdout = first_stdin_bytes
            
            # 为每个命令创建一个进程
            for i, cmd in enumerate(commands):
                cmd_description = f"{description} - 子命令 {i+1}/{len(commands)}: {cmd}"
                
                # 创建进程
                process = await self.create_process(
                    shell_cmd=cmd,  # 单个命令
                    directory=directory,
                    description=cmd_description,
                    labels=labels,
                    encoding=encoding,
                    timeout=timeout,
                )
                processes.append(process)
                
                # 执行当前进程，将前一个进程的输出作为输入
                try:
                    stdout, stderr = await self.execute_with_timeout(
                        process,
                        stdin=prev_stdout,
                        timeout=timeout
                    )
                    
                    # 累积错误输出
                    final_stderr += stderr if stderr else b""
                    
                    # 检查进程退出状态
                    if process.returncode != 0:
                        error_msg = stderr.decode(encoding or 'utf-8', errors='replace').strip()
                        if not error_msg:
                            error_msg = f"命令失败，退出码 {process.returncode}"
                        raise ValueError(error_msg)
                    
                    # 最后一个进程的输出是最终输出
                    if i == len(commands) - 1:
                        final_stdout = stdout if stdout else b""
                    else:
                        # 将当前进程的输出作为下一个进程的输入
                        prev_stdout = stdout if stdout else b""
                        
                except asyncio.TimeoutError:
                    # 超时发生，确保所有进程都被终止
                    for p in processes:
                        if p.returncode is None:
                            p.kill()
                    raise
                except Exception as e:
                    # 其他错误，确保所有进程都被终止
                    for p in processes:
                        if p.returncode is None:
                            p.kill()
                    raise e
            
            # 获取最后一个进程的退出码
            return_code = processes[-1].returncode if processes else 1
            
            return final_stdout, final_stderr, return_code
        
        finally:
            # 确保所有进程都被清理
            for process in processes:
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception as e:
                        logger.warning(f"清理管道进程时出错: {e}")

    async def get_process_status_summary(self) -> Dict[str, int]:
        """获取所有进程的状态摘要
        
        Returns:
            Dict[str, int]: 包含每种状态的进程数量，例如 {"running": 2, "completed": 3}
        """
        summary = {status.value: 0 for status in ProcessStatus}
        
        for process in self._processes.values():
            summary[process.status.value] += 1
            
        return summary


    def schedule_delayed_cleanup(self, pid: int) -> None:
        """为已完成的进程安排延迟清理
        
        Args:
            pid: 进程PID
        """
        bg_process = self._processes.get(pid)
        if not bg_process:
            logger.warning(f"无法安排清理：PID为 {pid} 的进程不存在")
            return
            
        # 如果该进程已经安排了清理，则跳过
        if bg_process.cleanup_scheduled:
            return
            
        # 设置清理标志
        bg_process.cleanup_scheduled = True
        
        # 使用asyncio创建延迟任务
        delay_seconds = self._auto_cleanup_age
        
        if delay_seconds <= 0:
            return  # 如果设置为0或负数，表示不自动清理
            
        logger.info(f"安排进程 {pid} 在 {delay_seconds} 秒后清理")
        
        loop = asyncio.get_event_loop()
        
        async def delayed_cleanup():
            try:
                await asyncio.sleep(delay_seconds)
                # 再次检查进程是否存在
                if pid in self._processes:
                    await self.clean_completed_process(pid)
            except Exception as e:
                logger.error(f"执行延迟清理时出错: {e}")
                
        # 创建任务
        def schedule_task():
            # 创建并返回任务
            task = loop.create_task(delayed_cleanup())
            bg_process.cleanup_handle = task
            return task
            
        # 如果在事件循环中，直接调度任务；否则，使用call_soon_threadsafe
        if loop.is_running():
            try:
                # 在事件循环中直接运行
                schedule_task()
            except RuntimeError:
                # 如果当前线程不是事件循环所在线程
                loop.call_soon_threadsafe(schedule_task)
        else:
            # 如果事件循环未运行（这种情况不应该发生）
            logger.warning("事件循环未运行，无法安排延迟清理")
            
        logger.debug(f"已为进程 {pid} 安排延迟清理")
