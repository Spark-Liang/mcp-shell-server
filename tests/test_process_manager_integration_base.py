import pytest
import asyncio
import os
import sys
import contextlib
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Tuple, AsyncGenerator

from mcp_shell_server.interfaces import IProcessManager

@contextlib.asynccontextmanager
async def get_process_manager(factory):
    """创建进程管理器并确保清理"""
    manager = factory()
    try:
        yield manager
    finally:
        await manager.cleanup_all()

class ProcessManagerTestBase(ABC):
    """IProcessManager接口实现的测试基类"""
    
    @abstractmethod
    def create_manager(self) -> IProcessManager:
        """创建被测实例的工厂方法，子类必须实现"""
        pass
    
    @pytest.mark.asyncio
    async def test_create_process(self):
        """测试创建进程的基本功能"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 运行echo命令
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Hello World"
            process = await process_manager.create_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
            )
            assert process is not None
            
            # 执行并验证输出
            stdout, stderr = await process_manager.execute_with_timeout(process)
            assert b"Hello World" in stdout
            assert stderr == b""
    
    @pytest.mark.asyncio
    async def test_execute_with_timeout_success(self):
        """测试成功执行带超时的进程"""
        async with get_process_manager(self.create_manager) as process_manager:
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Timeout Test"
            process = await process_manager.create_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
            )
            
            stdout, stderr = await process_manager.execute_with_timeout(
                process,
                timeout=5,
            )
            
            assert b"Timeout Test" in stdout
            assert stderr == b""
    
    @pytest.mark.asyncio
    async def test_execute_with_timeout_timeout(self):
        """测试执行超时的情况"""
        async with get_process_manager(self.create_manager) as process_manager:
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} sleep 2"
            process = await process_manager.create_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
            )
            
            with pytest.raises(TimeoutError):
                await process_manager.execute_with_timeout(
                    process,
                    timeout=0.1,  # 设置一个很小的超时时间
                )
    
    @pytest.mark.asyncio
    async def test_execute_pipeline_success(self):
        """测试成功执行管道命令"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 构建管道命令
            cmd1 = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Pipeline Test"
            cmd2 = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} grep Test"
            
            stdout, stderr, return_code = await process_manager.execute_pipeline(
                [cmd1, cmd2],
                directory=os.getcwd(),
            )
            
            assert b"Pipeline Test" in stdout
            assert stderr == b""
            assert return_code == 0
    
    @pytest.mark.asyncio
    async def test_execute_pipeline_empty(self):
        """测试执行空管道命令列表"""
        async with get_process_manager(self.create_manager) as process_manager:
            with pytest.raises(ValueError, match="No commands provided"):
                await process_manager.execute_pipeline(
                    [],
                    directory=os.getcwd(),
                )
    
    @pytest.mark.asyncio
    async def test_cleanup_processes(self):
        """测试清理进程"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 创建一个长时间运行的进程
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} sleep 10"
            process = await process_manager.create_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
            )
            
            # 确保进程在运行
            assert process.returncode is None
            
            # 清理进程
            await process_manager.cleanup_processes([process])
            
            # 等待进程结束
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
                # 验证进程已被终止
                assert process.returncode is not None
            except asyncio.TimeoutError:
                pytest.fail("Process was not cleaned up properly")
    
    @pytest.mark.asyncio
    async def test_process_encoding(self):
        """测试进程的编码处理功能"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 使用encode_echo命令测试不同编码
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} encode_echo 测试文本"
            
            # 指定UTF-8编码
            process_utf8 = await process_manager.create_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                encoding="utf-8"
            )
            
            stdout_utf8, stderr_utf8 = await process_manager.execute_with_timeout(process_utf8)
            
            # 验证输出不为空且错误输出为空
            assert len(stdout_utf8) > 0
            assert stderr_utf8 == b""
            
            # 测试不同的编码参数
            if sys.platform == "win32":
                # Windows平台测试GBK编码
                cmd_gbk = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} encode_echo 测试GBK编码"
                process_gbk = await process_manager.create_process(
                    shell_cmd=cmd_gbk,
                    directory=os.getcwd(),
                    encoding="gbk"  # 在Windows上指定GBK编码
                )
                
                stdout_gbk, stderr_gbk = await process_manager.execute_with_timeout(process_gbk)
                
                # 验证输出不为空且错误输出为空
                assert len(stdout_gbk) > 0
                assert stderr_gbk == b"" 