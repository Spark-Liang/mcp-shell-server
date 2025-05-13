import pytest
import asyncio
import os
import sys
from datetime import datetime

from mcp_shell_server.background_process_manager import BackgroundProcessManager
from mcp_shell_server.interfaces import ProcessStatus
from .test_process_manager_integration_base import ProcessManagerTestBase, get_process_manager

class TestBackgroundProcessManager(ProcessManagerTestBase):
    """BackgroundProcessManager的测试实现"""
    
    def create_manager(self):
        """创建BackgroundProcessManager实例"""
        return BackgroundProcessManager()
    
    @pytest.mark.asyncio
    async def test_start_process(self):
        """测试启动进程并获取ID"""
        async with get_process_manager(self.create_manager) as process_manager:
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Hello Background"
            pid = await process_manager.start_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                description="测试进程",
                labels=["test"],
            )
            
            # 验证进程ID是否有效
            assert pid is not None
            assert isinstance(pid, int)
            
            # 获取进程对象
            bg_process = await process_manager.get_process(pid)
            assert bg_process is not None
            
            # 等待进程完成
            try:
                await asyncio.wait_for(bg_process.wait(), timeout=5.0)
                # 验证进程已完成
                assert bg_process.returncode == 0
            except asyncio.TimeoutError:
                pytest.fail("Process did not complete in time")
    
    @pytest.mark.asyncio
    async def test_list_processes(self):
        """测试列出进程"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 创建一些进程
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Test Process"
            pid1 = await process_manager.start_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                description="Test process 1",
                labels=["test", "echo"],
            )
            
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} sleep 0.5"
            pid2 = await process_manager.start_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                description="Test process 2",
                labels=["test", "sleep"],
            )
            
            # 等待第一个进程完成
            bg_process1 = await process_manager.get_process(pid1)
            await asyncio.wait_for(bg_process1.wait(), timeout=5.0)
            
            # 测试按标签过滤
            processes = await process_manager.list_processes(labels=["echo"])
            assert len(processes) == 1
            assert processes[0].description == "Test process 1"
            
            # 测试按状态过滤
            processes = await process_manager.list_processes(status=ProcessStatus.RUNNING)
            assert len(processes) >= 1  # 至少有一个正在运行的进程
            
            # 等待所有进程完成
            await asyncio.sleep(1)  # 确保所有进程有时间完成
    
    @pytest.mark.asyncio
    async def test_get_process_output(self):
        """测试获取进程输出"""
        async with get_process_manager(self.create_manager) as process_manager:
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} echo Output Test"
            pid = await process_manager.start_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                description="Output test process",
            )
            
            # 等待进程完成
            bg_process = await process_manager.get_process(pid)
            await asyncio.wait_for(bg_process.wait(), timeout=5.0)
            
            # 获取输出
            output = await process_manager.get_process_output(pid)
            
            # 验证输出
            assert len(output) > 0
            assert any("Output Test" in entry.text for entry in output)
    
    @pytest.mark.asyncio
    async def test_stop_process(self):
        """测试停止进程"""
        async with get_process_manager(self.create_manager) as process_manager:
            # 创建一个长时间运行的进程
            cmd = f"{sys.executable} {os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')} sleep 10"
            pid = await process_manager.start_process(
                shell_cmd=cmd,
                directory=os.getcwd(),
                description="Long running process",
            )
            
            # 停止进程
            result = await process_manager.stop_process(pid)
            assert result is True
            
            # 验证进程已停止
            bg_process = await process_manager.get_process(pid)
            assert bg_process.status == ProcessStatus.TERMINATED 