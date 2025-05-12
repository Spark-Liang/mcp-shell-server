"""Background process management for shell command execution."""

import asyncio
import logging
import os
import signal
import uuid
import tempfile
from enum import Enum, auto
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Any, Union, IO, Tuple, AsyncGenerator

from pydantic import BaseModel, Field, field_validator

from mcp_shell_server.output_manager import OutputManager
from mcp_shell_server.env_name_const import PROCESS_RETENTION_SECONDS

logger = logging.getLogger("mcp-shell-server")

# 进程状态枚举
class ProcessStatus(str, Enum):
    """进程状态枚举"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"
    ERROR = "error"


class BackgroundProcess:
    """表示一个后台运行的进程"""
    def __init__(self, 
                process_id: str, 
                command: str, 
                directory: str,
                description: str,  # 描述是必填项
                labels: Optional[List[str]] = None,
                process: Optional[asyncio.subprocess.Process] = None,
                encoding: Optional[str] = None,
                timeout: Optional[int] = None):  # 添加超时参数
        """初始化后台进程对象
        
        Args:
            process_id: 进程唯一标识符
            command: 要执行的命令字符串
            directory: 工作目录
            description: 进程描述(必填)
            labels: 用于分类的标签列表
            process: asyncio子进程对象
            encoding: 输出字符编码
            timeout: 超时时间(秒)
        """
        self.process_id = process_id  # 随机字符串作为唯一标识
        self.command = command  # 命令字符串
        self.directory = directory  # 工作目录
        self.description = description  # 命令描述
        self.labels = labels or []  # 标签列表
        self.process = process  # 实际的进程对象
        self.encoding = encoding or 'utf-8'  # 字符编码，默认utf-8
        self.start_time = datetime.now()  # 启动时间
        self.timeout = timeout  # 超时时间(秒)
        
        # 创建临时目录用于存储日志文件
        self.log_dir = os.path.join(tempfile.gettempdir(), f"mcp_shell_logs_{process_id}")
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

    def get_info(self) -> Dict[str, Any]:
        """获取进程基本信息
        
        Returns:
            dict: 包含进程基本信息的字典
        """
        return {
            "process_id": self.process_id,
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
    
    def get_output(self, tail: Optional[int] = None, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """获取标准输出
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的输出
            until: 只返回指定时间之前的输出
            
        Returns:
            输出列表
        """
        # 使用OutputLogger获取日志
        return self._stdout_logger.get_logs(tail=tail, since=since, until=until)
    
    def get_error(self, tail: Optional[int] = None, since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """获取错误输出
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的输出
            until: 只返回指定时间之前的输出
            
        Returns:
            错误输出列表
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


class BackgroundProcessManager:
    """管理后台进程的创建、执行和清理。"""

    def __init__(self):
        """初始化BackgroundProcessManager，设置信号处理。"""
        # 使用字典存储进程，便于通过ID访问
        self._processes: Dict[str, BackgroundProcess] = {}
        self._original_sigint_handler = None
        self._original_sigterm_handler = None
        self._setup_signal_handlers()
        
        # 进程保留时间设置（秒）
        self._auto_cleanup_age = int(os.environ.get(PROCESS_RETENTION_SECONDS, 3600))  # 默认1小时

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器，用于优雅地管理进程。"""
        if os.name != "posix":
            return

        def handle_termination(signum: int, _: Any) -> None:
            """处理终止信号，清理进程。"""
            if self._processes:
                for process_id, bg_process in list(self._processes.items()):
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
                            logger.warning(f"进程 {bg_process.process_id} 执行超时 ({bg_process.timeout}秒)")
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
                    self.schedule_delayed_cleanup(bg_process.process_id)
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
            self.schedule_delayed_cleanup(bg_process.process_id)
            
        except Exception as e:
            logger.error(f"监控进程时出错: {e}")
            bg_process.status = ProcessStatus.ERROR
            bg_process.end_time = datetime.now()
            
            # 进程出错，安排延迟清理
            self.schedule_delayed_cleanup(bg_process.process_id)
            
            # 确保进程已终止
            if bg_process.process and bg_process.process.returncode is None:
                try:
                    bg_process.process.kill()
                except Exception:
                    pass

    async def create_process(
        self,
        command: str,
        directory: str,
        description: str,
        labels: Optional[List[str]] = None,
        stdin: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> BackgroundProcess:
        """创建一个新的后台进程。

        Args:
            command: 要执行的命令字符串
            directory: 工作目录
            description: 进程描述
            labels: 进程标签列表
            stdin: 传递给进程的输入
            envs: 额外的环境变量
            encoding: 输出编码
            timeout: 超时时间（秒）

        Returns:
            BackgroundProcess: 创建的后台进程对象

        Raises:
            ValueError: 如果进程创建失败
        """
        process_id = str(uuid.uuid4())[:5]
        shell_cmd = command
        
        # 记录进程启动详细信息
        logger.info(f"启动进程 {process_id}:")
        logger.info(f"  命令: {shell_cmd}")
        logger.info(f"  工作目录: {directory}")
        if envs:
            logger.info(f"  环境变量: {envs}")
        logger.info(f"  描述: {description}")
        if labels:
            logger.info(f"  标签: {labels}")
        if encoding:
            logger.info(f"  编码: {encoding}")
        if timeout:
            logger.info(f"  超时: {timeout}秒")
        
        try:
            # 创建实际的子进程
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **(envs or {})},
                cwd=directory,
            )

            # 创建后台进程对象
            bg_process = BackgroundProcess(
                process_id=process_id,
                command=command,
                directory=directory,
                description=description,
                labels=labels,
                process=process,
                encoding=encoding,
                timeout=timeout,  # 传递超时参数
            )
            
            # 将进程添加到管理的字典中
            self._processes[process_id] = bg_process
            
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
        command: str,
        directory: str,
        description: str,
        labels: Optional[List[str]] = None,
        stdin: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """启动一个后台进程并返回其ID。

        Args:
            command: 要执行的命令字符串
            directory: 工作目录
            description: 命令描述(必填)
            labels: 标签列表
            stdin: 标准输入
            envs: 环境变量
            encoding: 字符编码
            timeout: 超时时间(秒)
            
        Returns:
            str: 进程ID
            
        Raises:
            ValueError: 如果进程创建失败
        """
        bg_process = await self.create_process(
            command=command,
            directory=directory,
            description=description,
            labels=labels,
            stdin=stdin,
            envs=envs,
            encoding=encoding,
            timeout=timeout,
        )
        
        return bg_process.process_id
        
    async def list_processes(self, labels: Optional[List[str]] = None, status: Optional[ProcessStatus] = None) -> List[Dict[str, Any]]:
        """列出进程，可按标签和状态过滤。
        
        Args:
            labels: 标签过滤条件
            status: 状态过滤条件
            
        Returns:
            List[Dict]: 进程信息列表
        """
        result = []
        
        for proc_id, bg_process in self._processes.items():
            # 如果指定了标签过滤，检查是否匹配
            if labels and not any(label in labels for label in bg_process.labels):
                continue
                
            # 如果指定了状态过滤，检查是否匹配
            if status and bg_process.status != status:
                continue
                
            # 添加进程信息到结果
            result.append(bg_process.get_info())
            
        return result
    
    async def get_process(self, process_id: str) -> Optional[BackgroundProcess]:
        """获取指定ID的进程对象。
        
        Args:
            process_id: 进程ID
            
        Returns:
            Optional[BackgroundProcess]: 进程对象，如果不存在则返回None
        """
        return self._processes.get(process_id)
        
    async def stop_process(self, process_id: str, force: bool = False) -> bool:
        """停止指定的进程。
        
        Args:
            process_id: 进程ID
            force: 是否强制停止
            
        Returns:
            bool: 是否成功停止
            
        Raises:
            ValueError: 进程不存在时抛出
        """
        if process_id not in self._processes:
            raise ValueError(f"进程ID {process_id} 不存在")
            
        bg_process = self._processes[process_id]
        
        # 如果进程已经不在运行状态，无需操作
        if not bg_process.is_running():
            # 确保为非运行状态的进程安排延迟清理
            self.schedule_delayed_cleanup(process_id)
            return True
            
        # 如果进程对象不存在，更新状态并返回
        if not bg_process.process:
            bg_process.status = ProcessStatus.TERMINATED
            bg_process.end_time = datetime.now()
            # 安排延迟清理
            self.schedule_delayed_cleanup(process_id)
            return True
            
        # 停止进程
        try:
            if force:
                if asyncio.iscoroutinefunction(bg_process.process.kill):
                    await bg_process.process.kill()
                else:
                    bg_process.process.kill()
            else:
                if asyncio.iscoroutinefunction(bg_process.process.terminate):
                    await bg_process.process.terminate()
                else:
                    bg_process.process.terminate()
                
            # 等待进程结束，有超时限制
            try:
                await asyncio.wait_for(bg_process.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                if not force:
                    # 如果超时且非强制模式，强制终止
                    if asyncio.iscoroutinefunction(bg_process.process.kill):
                        await bg_process.process.kill()
                    else:
                        bg_process.process.kill()
                    await asyncio.wait_for(bg_process.process.wait(), timeout=2.0)
                    
            # 更新进程状态
            bg_process.status = ProcessStatus.TERMINATED
            bg_process.end_time = datetime.now()
            if bg_process.process:
                bg_process.exit_code = bg_process.process.returncode
                
            # 安排延迟清理
            self.schedule_delayed_cleanup(process_id)
                    
            return True
        except Exception as e:
            logger.error(f"停止进程时出错: {e}")
            raise ValueError(f"停止进程时出错: {str(e)}")
    
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
        """
        if process_id not in self._processes:
            raise ValueError(f"进程ID {process_id} 不存在")
            
        bg_process = self._processes[process_id]
        
        # 解析since参数
        since = None
        if since_time:
            try:
                since = datetime.fromisoformat(since_time)
            except ValueError:
                raise ValueError("'since_time' 必须是有效的ISO格式时间字符串 (例如: '2021-01-01T00:00:00')")
        
        # 解析until参数
        until = None
        if until_time:
            try:
                until = datetime.fromisoformat(until_time)
            except ValueError:
                raise ValueError("'until_time' 必须是有效的ISO格式时间字符串 (例如: '2021-01-01T00:00:00')")
        
        # 获取输出
        if error:
            return bg_process.get_error(tail=tail, since=since, until=until)
        else:
            return bg_process.get_output(tail=tail, since=since, until=until)
    
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
        """
        process = await self.get_process(process_id)
        if not process:
            raise ValueError(f"进程 {process_id} 不存在")
        
        # 转换since_time
        since_dt = None
        if since_time:
            try:
                since_dt = datetime.fromisoformat(since_time)
            except ValueError:
                raise ValueError(f"无效的时间格式: {since_time}，应为ISO格式")
        
        # 转换until_time
        until_dt = None
        if until_time:
            try:
                until_dt = datetime.fromisoformat(until_time)
            except ValueError:
                raise ValueError(f"无效的时间格式: {until_time}，应为ISO格式")
        
        # 获取标准输出和错误输出
        stdout_output = process.get_output(tail=None, since=since_dt, until=until_dt)
        stderr_output = process.get_error(tail=None, since=since_dt, until=until_dt)
        
        # 合并输出并按时间排序
        combined = []
        for item in stdout_output:
            # 确保since_time过滤
            if since_dt and item["timestamp"] < since_dt:
                continue
            # 确保until_time过滤
            if until_dt and item["timestamp"] > until_dt:
                continue
            combined.append({
                "timestamp": item["timestamp"],
                "text": item["text"],
                "stream": "stdout"
            })
        
        for item in stderr_output:
            # 确保since_time过滤
            if since_dt and item["timestamp"] < since_dt:
                continue
            # 确保until_time过滤
            if until_dt and item["timestamp"] > until_dt:
                continue
            combined.append({
                "timestamp": item["timestamp"],
                "text": item["text"],
                "stream": "stderr"
            })
        
        # 按时间戳排序
        combined.sort(key=lambda x: x["timestamp"])
        
        # 应用tail限制（在排序后）
        if tail is not None:
            combined = combined[-tail:]
            
        return combined
    
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
        """
        # 获取进程对象
        process = await self.get_process(process_id)
        if not process:
            raise ValueError(f"进程 {process_id} 不存在")
        
        # 转换since_time为datetime对象
        since_dt = None
        if since_time:
            try:
                since_dt = datetime.fromisoformat(since_time)
            except ValueError:
                raise ValueError(f"无效的时间格式: {since_time}，应为ISO格式")
        
        # 获取初始输出
        last_outputs = []
        if error:
            # 处理get_error可能是协程的情况
            if asyncio.iscoroutinefunction(process.get_error):
                last_outputs = await process.get_error(tail=tail, since=since_dt)
            else:
                last_outputs = process.get_error(tail=tail, since=since_dt)
        else:
            # 处理get_output可能是协程的情况
            if asyncio.iscoroutinefunction(process.get_output):
                last_outputs = await process.get_output(tail=tail, since=since_dt)
            else:
                last_outputs = process.get_output(tail=tail, since=since_dt)
        
        # 首先发送已有的行
        for output in last_outputs:
            yield output
        
        # 记录最后一行的时间戳，用于过滤
        last_timestamp = datetime.min
        if last_outputs:
            last_timestamp = last_outputs[-1]["timestamp"]
            
        # 持续轮询新输出，直到进程结束
        while process.is_running():
            # 获取上次之后的新输出
            new_outputs = []
            if error:
                # 处理get_error可能是协程的情况
                if asyncio.iscoroutinefunction(process.get_error):
                    all_outputs = await process.get_error()
                else:
                    all_outputs = process.get_error()
                new_outputs = [
                    output for output in all_outputs 
                    if output["timestamp"] > last_timestamp
                ]
            else:
                # 处理get_output可能是协程的情况
                if asyncio.iscoroutinefunction(process.get_output):
                    all_outputs = await process.get_output()
                else:
                    all_outputs = process.get_output()
                new_outputs = [
                    output for output in all_outputs 
                    if output["timestamp"] > last_timestamp
                ]
                
            # 发送新输出
            for output in new_outputs:
                yield output
                last_timestamp = max(last_timestamp, output["timestamp"])
                
            # 等待下一次轮询
            await asyncio.sleep(poll_interval)
        
        # 进程结束后，再获取一次是否有新输出
        final_outputs = []
        if error:
            # 处理get_error可能是协程的情况
            if asyncio.iscoroutinefunction(process.get_error):
                all_outputs = await process.get_error()
            else:
                all_outputs = process.get_error()
            final_outputs = [
                output for output in all_outputs 
                if output["timestamp"] > last_timestamp
            ]
        else:
            # 处理get_output可能是协程的情况
            if asyncio.iscoroutinefunction(process.get_output):
                all_outputs = await process.get_output()
            else:
                all_outputs = process.get_output()
            final_outputs = [
                output for output in all_outputs 
                if output["timestamp"] > last_timestamp
            ]
            
        # 发送最终输出
        for output in final_outputs:
            yield output
    
    async def cleanup_processes(self, labels: Optional[List[str]] = None, status: Optional[ProcessStatus] = None) -> int:
        """清理已完成的进程，可按标签和状态过滤。
        
        Args:
            labels: 标签过滤条件
            status: 状态过滤条件（默认清理所有非running状态的进程）
            
        Returns:
            int: 清理的进程数量
        """
        to_remove = []
        
        # 查找已完成的进程
        for proc_id, bg_process in self._processes.items():
            # 如果进程仍在运行，且未指定状态，跳过
            if bg_process.is_running() and not status:
                continue
                
            # 如果指定了状态过滤，检查是否匹配
            if status and bg_process.status != status:
                continue
                
            # 如果指定了标签过滤，检查是否匹配
            if labels and not any(label in labels for label in bg_process.labels):
                continue
                
            to_remove.append(proc_id)
            
        # 移除进程
        for proc_id in to_remove:
            await self.cleanup_process(proc_id)
            del self._processes[proc_id]
            
        return len(to_remove)

    async def cleanup_process(self, process_id: str) -> None:
        """清理特定的进程。

        Args:
            process_id: 要清理的进程ID
        """
        if process_id in self._processes:
            bg_process = self._processes[process_id]
            
            # 取消监控任务
            if bg_process.monitor_task and not bg_process.monitor_task.done():
                bg_process.monitor_task.cancel()
                try:
                    await bg_process.monitor_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(f"取消监控任务时出错: {e}")
            
            # 取消流读取任务
            tasks = []
            if bg_process.stdout_task and not bg_process.stdout_task.done():
                bg_process.stdout_task.cancel()
                tasks.append(bg_process.stdout_task)
                
            if bg_process.stderr_task and not bg_process.stderr_task.done():
                bg_process.stderr_task.cancel()
                tasks.append(bg_process.stderr_task)
                
            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    logger.warning(f"取消流读取任务时出错: {e}")
            
            # 终止进程
            if bg_process.process and bg_process.process.returncode is None:
                try:
                    # 先尝试优雅终止
                    if asyncio.iscoroutinefunction(bg_process.process.terminate):
                        await bg_process.process.terminate()
                    else:
                        bg_process.process.terminate()
                    try:
                        await asyncio.wait_for(bg_process.process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        # 如果超时，强制终止
                        if asyncio.iscoroutinefunction(bg_process.process.kill):
                            await bg_process.process.kill()
                        else:
                            bg_process.process.kill()
                        await asyncio.wait_for(bg_process.process.wait(), timeout=1.0)
                except Exception as e:
                    logger.warning(f"终止进程时出错: {e}")
            
            # 更新进程状态
            bg_process.status = ProcessStatus.TERMINATED
            bg_process.end_time = datetime.now()
            if bg_process.process:
                bg_process.exit_code = bg_process.process.returncode
                
            # 清理日志文件
            bg_process.cleanup()

    async def clean_completed_process(self, process_id: str) -> bool:
        """清理已完成的进程。只有当进程已经结束时才会清理，运行中的进程会报错。
        
        Args:
            process_id: 要清理的进程ID
            
        Returns:
            bool: 清理是否成功
            
        Raises:
            ValueError: 如果进程不存在或进程仍在运行
        """
        if process_id not in self._processes:
            raise ValueError(f"进程ID {process_id} 不存在")
            
        bg_process = self._processes[process_id]
        
        # 检查进程是否已结束
        if bg_process.is_running():
            raise ValueError(f"进程 {process_id} 仍在运行中，无法清理")
            
        # 清理进程资源
        await self.cleanup_process(process_id)
        
        # 从进程字典中删除
        del self._processes[process_id]
        
        return True

    async def cleanup_all(self) -> None:
        """清理所有被跟踪的进程。"""
        # 取消所有已安排的延迟清理任务
        for proc_id, bg_proc in self._processes.items():
            if bg_proc.cleanup_handle and not bg_proc.cleanup_handle.cancelled():
                bg_proc.cleanup_handle.cancel()
                bg_proc.cleanup_scheduled = False
        
        # 停止所有运行中的进程
        running_processes = [
            proc_id for proc_id, bg_proc in self._processes.items()
            if bg_proc.is_running()
        ]
        
        for proc_id in running_processes:
            try:
                await self.stop_process(proc_id, force=True)
            except Exception as e:
                logger.warning(f"停止进程 {proc_id} 时出错: {e}")
        
        # 清理所有进程资源
        for process_id in list(self._processes.keys()):
            await self.cleanup_process(process_id)
            
        # 清空进程字典
        self._processes.clear()

    async def execute_pipeline(
        self,
        commands: List[str],
        directory: str,
        description: str,
        labels: Optional[List[str]] = None,
        first_stdin: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        encoding: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """执行管道命令序列，将多个命令的执行连接起来。
        
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
            str: 创建的后台进程ID
            
        Raises:
            ValueError: 如果命令列表为空或进程创建失败
        """
        if not commands:
            raise ValueError("命令列表不能为空")
            
        # 构建管道命令字符串
        pipeline_cmd = " | ".join(commands)
        
        # 构建描述
        if not description:
            description = f"管道命令: {pipeline_cmd}"
            
        # 创建进程
        process_id = await self.start_process(
            command=pipeline_cmd,  # 作为单个命令传递
            directory=directory,
            description=description,
            labels=labels,
            stdin=first_stdin,
            envs=envs,
            encoding=encoding,
            timeout=timeout,
        )
        
        return process_id

    async def get_process_status_summary(self) -> Dict[str, int]:
        """获取所有进程的状态摘要
        
        Returns:
            Dict[str, int]: 包含每种状态的进程数量，例如 {"running": 2, "completed": 3}
        """
        summary = {status.value: 0 for status in ProcessStatus}
        
        for process in self._processes.values():
            summary[process.status.value] += 1
            
        return summary


    def schedule_delayed_cleanup(self, process_id: str) -> None:
        """为进程安排延迟清理任务
        
        Args:
            process_id: 要安排清理的进程ID
        """
        if process_id not in self._processes:
            logger.warning(f"尝试为不存在的进程 {process_id} 安排清理任务")
            return
            
        bg_process = self._processes[process_id]
        
        # 如果进程还在运行或已经安排了清理，则跳过
        if bg_process.is_running() or bg_process.cleanup_scheduled:
            return
            
        # 取消已存在的清理任务
        if bg_process.cleanup_handle and not bg_process.cleanup_handle.cancelled():
            bg_process.cleanup_handle.cancel()
            
        # 获取延迟清理时间（秒）
        retention_seconds = self._auto_cleanup_age
        if retention_seconds <= 0:
            return  # 如果保留时间设为0或负数，不自动清理
            
        try:
            # 使用loop.call_later安排延迟清理
            loop = asyncio.get_running_loop()
            
            # 创建一个延迟清理的协程封装函数
            async def delayed_cleanup():
                try:
                    # 记录日志
                    logger.info(f"执行延迟清理进程 {process_id}")
                    
                    # 检查进程是否仍然存在
                    if process_id in self._processes:
                        # 清理进程资源
                        await self.cleanup_process(process_id)
                        del self._processes[process_id]
                except Exception as e:
                    logger.error(f"延迟清理进程 {process_id} 时出错: {e}")
                finally:
                    # 完成清理任务后重置标记
                    if process_id in self._processes:
                        self._processes[process_id].cleanup_scheduled = False
                        self._processes[process_id].cleanup_handle = None
            
            # 创建任务包装器，在延迟后执行清理
            def schedule_task():
                # 创建并返回任务
                task = asyncio.create_task(delayed_cleanup())
                return task
                
            # 使用call_later安排延迟执行
            bg_process.cleanup_handle = loop.call_later(
                retention_seconds, 
                schedule_task
            )
            bg_process.cleanup_scheduled = True
            
            logger.debug(f"已为进程 {process_id} 安排延迟清理，将在 {retention_seconds} 秒后执行")
        except RuntimeError:
            # 没有运行中的事件循环，跳过延迟清理
            logger.debug(f"没有检测到运行中的事件循环，跳过为进程 {process_id} 安排延迟清理")
        except Exception as e:
            logger.error(f"安排进程 {process_id} 延迟清理时出错: {e}")
