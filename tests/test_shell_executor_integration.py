import pytest
import asyncio
import os
import sys
import time
import tempfile
from typing import List, Optional

from mcp_shell_server.shell_executor import ShellExecutor, ShellCommandResponse


class TestShellExecutorIntegration:
    """ShellExecutor类的集成测试"""
    
    def setup_method(self):
        """测试前设置"""
        # 设置允许执行的命令，包括Python解释器的完整路径
        python_path = sys.executable
        if sys.platform == "win32":
            os.environ["ALLOW_COMMANDS"] = f"echo,cmd.exe,ping,findstr,type,powershell.exe,python,{python_path}"
        else:
            os.environ["ALLOW_COMMANDS"] = f"echo,sh,bash,sleep,grep,cat,python,python3,{python_path}"
        
        self.shell_executor = ShellExecutor()
        self.cmd_for_test_path = os.path.join(os.path.dirname(__file__), 'cmd_for_test.py')
        self.test_dir = os.getcwd()
    
    @pytest.fixture(autouse=True)
    async def _setup_and_teardown(self, event_loop):
        """自动使用的fixture，确保正确设置和清理"""
        # 使用传入的事件循环避免嵌套循环问题
        yield
        # 测试后清理
        await self.shell_executor.process_manager.cleanup_all()
    
    @pytest.mark.asyncio
    async def test_basic_execute(self):
        """测试基本的命令执行功能"""
        # 使用原生的echo命令测试基本执行
        if sys.platform == "win32":
            cmd = ["echo", "Hello World"]
        else:
            cmd = ["echo", "Hello World"]
        
        response = await self.shell_executor.execute(
            command=cmd,
            directory=self.test_dir
        )
        
        assert response.error is None, f"Error: {response.error}"
        assert "Hello World" in response.stdout
        assert response.stderr == ""
        assert response.status == 0
    
    @pytest.mark.asyncio
    async def test_execute_with_timeout_success(self):
        """测试带超时的成功执行"""
        # 使用短时间运行的命令
        cmd = ["echo", "Timeout Test"]
        
        response = await self.shell_executor.execute(
            command=cmd,
            directory=self.test_dir,
            timeout=5
        )
        
        assert response.error is None, f"Error: {response.error}"
        assert "Timeout Test" in response.stdout
        assert response.stderr == ""
        assert response.status == 0
    
    @pytest.mark.asyncio
    async def test_execute_with_timeout_failure(self):
        """测试执行超时的情况"""
        # 使用长时间运行的命令
        if sys.platform == "win32":
            cmd = ["ping", "-n", "10", "127.0.0.1"]  # 在Windows上使用ping命令
        else:
            cmd = ["sleep", "10"]  # Unix上的休眠命令
        
        response = await self.shell_executor.execute(
            command=cmd,
            directory=self.test_dir,
            timeout=1  # 设置较短的超时时间
        )
        
        # 验证是否因超时而失败
        assert response.error is not None, "Expected timeout error but got none"
        assert "timed out" in response.error.lower() or "timeout" in response.error.lower()
        assert response.status == -1
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32", reason="Windows平台上的管道命令测试暂时跳过")
    async def test_execute_pipeline(self):
        """测试执行包含管道的命令"""
        # 使用文件和多个命令模拟管道操作
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as temp:
            temp.write("Pipeline Test\nOther Line\n")
            temp_path = temp.name
        
        try:
            if sys.platform == "win32":
                # Windows上使用type和findstr
                response = await self.shell_executor.execute(
                    command=["powershell.exe", "-Command", f"Get-Content {temp_path} | Select-String Test"],
                    directory=self.test_dir
                )
            else:
                # Unix上使用cat和grep
                response = await self.shell_executor.execute(
                    command=["bash", "-c", f"cat {temp_path} | grep Test"],
                    directory=self.test_dir
                )
            
            assert response.error is None, f"Error: {response.error}"
            assert "Pipeline Test" in response.stdout
            assert response.status == 0
        finally:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32", reason="Windows平台上的编码测试暂时跳过")
    async def test_execute_with_encoding(self):
        """测试使用不同编码执行命令"""
        # 中文测试文本
        test_text = "测试编码"
        
        if sys.platform == "win32":
            # Windows上创建一个包含中文的文件，然后读取它
            with tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', delete=False, suffix='.txt') as temp:
                temp.write(test_text)
                temp_path = temp.name
            
            try:
                # 使用UTF-8编码读取文件
                response_utf8 = await self.shell_executor.execute(
                    command=["type", temp_path],
                    directory=self.test_dir,
                    encoding="utf-8"
                )
                
                # 使用GBK编码读取文件
                response_gbk = await self.shell_executor.execute(
                    command=["type", temp_path],
                    directory=self.test_dir,
                    encoding="gbk"
                )
                
                # 至少有一种编码应该能正确读取
                assert test_text in response_utf8.stdout or test_text in response_gbk.stdout, \
                    "中文字符无法正确读取"
            finally:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        else:
            # Unix系统上使用echo和UTF-8编码
            response = await self.shell_executor.execute(
                command=["echo", test_text],
                directory=self.test_dir,
                encoding="utf-8"
            )
            
            assert test_text in response.stdout
    
    @pytest.mark.asyncio
    async def test_async_execute(self):
        """测试异步执行功能"""
        # 运行一个简单的命令
        if sys.platform == "win32":
            cmd = ["echo", "Async Test"]
        else:
            cmd = ["echo", "Async Test"]
            
        # 使用async_execute方法启动进程
        pid = await self.shell_executor.async_execute(
            command=cmd,
            directory=self.test_dir
        )
        
        # 验证返回的进程ID
        assert pid is not None, "进程ID不应为空"
        assert isinstance(pid, int), "进程ID应该是整数"
        assert pid > 0, "进程ID应该是正数"
        
        # 等待进程完成
        processes = await self.shell_executor.list_processes()
        process = next(p for p in processes if p.pid == pid)
        
        # 等待一小段时间让进程完成
        for _ in range(10):
            if process.status != "running":
                break
            await asyncio.sleep(0.1)
        
        # 获取进程输出
        log_entries = await self.shell_executor.get_process_output(pid)
        
        # 验证输出
        assert log_entries, "日志条目不应为空"
        assert any("Async Test" in entry.text for entry in log_entries), "输出中应该包含命令结果"
    
    @pytest.mark.asyncio
    async def test_process_management(self):
        """测试进程管理功能"""
        # 启动一个长时间运行的进程
        if sys.platform == "win32":
            cmd = ["ping", "-n", "10", "127.0.0.1"]  # 持续10秒
        else:
            cmd = ["sleep", "10"]
            
        # 启动进程
        pid = await self.shell_executor.async_execute(
            command=cmd,
            directory=self.test_dir
        )
        
        # 验证进程已经启动
        assert pid is not None, "进程ID不应为空"
        
        # 列出所有进程
        processes = await self.shell_executor.list_processes()
        assert len(processes) > 0, "进程列表不应为空"
        
        # 获取指定进程
        process = await self.shell_executor.get_process(pid)
        assert process is not None, "应该能够获取到已启动的进程"
        assert process.pid == pid, "进程ID应该匹配"
        
        # 停止进程
        success = await self.shell_executor.stop_process(pid)
        assert success, "停止进程应该成功"
        
        # 等待进程终止
        for _ in range(10):
            process = await self.shell_executor.get_process(pid)
            if process is None or process.returncode is not None:
                break
            await asyncio.sleep(0.1)
        
        # 验证进程已终止
        process = await self.shell_executor.get_process(pid)
        assert process is None or process.returncode is not None, "进程应该已终止"
        
        # 清理指定的已完成的进程
        success = await self.shell_executor.clean_completed_process(pid)
        assert success, "清理指定进程应该成功"
    
    @pytest.mark.asyncio
    async def test_execute_binary_cat_with_chinese(self):
        """测试使用python执行cmd_for_test.py的binary_cat工具命令读取包含中文字符的文件"""
        # 中文测试文本
        test_text = "这是一段中文文本，用于测试 binary_cat 命令的读取能力。"
        
        
        temp_path = None
        try:
            encoding = "utf-8"
            if sys.platform == "win32":
                encoding = "gbk"

            # 构建命令
            python_cmd = sys.executable
            cmd_path = self.cmd_for_test_path
            
            # 创建一个包含中文的临时文件
            with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, delete=False, suffix='.txt') as temp:
                temp.write(test_text)
                temp_path = temp.name

            # 使用execute方法运行python执行cmd_for_test.py的binary_cat命令
            cmd = [python_cmd, cmd_path, "binary_cat", temp_path]


            # 使用默认编码
            response = await self.shell_executor.execute(
                command=cmd,
                directory=self.test_dir,
                encoding=encoding  # 使用UTF-8编码处理输出
            )
            
            # 验证输出
            print(encoding)
            print(response)
            assert response.error is None, f"Error: {response.error}"
            assert test_text in response.stdout, "应该能正确读取中文文本"
            assert response.status == 0, "执行应该成功"
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.unlink(temp_path) 