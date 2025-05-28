import os
import sys

import pytest

# 确保tests目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_shell_server.process_manager import ProcessManager

from .test_process_manager_integration_base import (
    ProcessManagerTestBase,
    get_process_manager,
)


class TestProcessManager(ProcessManagerTestBase):
    """ProcessManager的测试实现"""

    def create_manager(self):
        """创建ProcessManager实例"""
        return ProcessManager()

    # 可以添加特定于ProcessManager的测试方法
    @pytest.mark.asyncio
    async def test_process_manager_specific_feature(self):
        """测试ProcessManager特有的功能"""
        # 这里可以添加特定于ProcessManager的测试
        async with get_process_manager(self.create_manager) as process_manager:
            assert isinstance(process_manager, ProcessManager)
