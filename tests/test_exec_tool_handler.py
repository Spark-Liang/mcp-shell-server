import asyncio
import os
import tempfile

import pytest
from mcp.types import TextContent, Tool

from mcp_shell_server.exec_tool_handler import ExecuteToolHandler, ShellExecuteArgs


# Mock process class
class MockProcess:
    def __init__(self, stdout=None, stderr=None, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self._input = None

    async def communicate(self, input=None):
        self._input = input
        if self._input and not isinstance(self._input, bytes):
            self._input = self._input.encode("utf-8")

        # For cat command, echo back the input
        if self.stdout is None and self._input:
            return self._input, self.stderr

        if isinstance(self.stdout, int):
            self.stdout = str(self.stdout).encode("utf-8")
        if self.stdout is None:
            self.stdout = b""
        if self.stderr is None:
            self.stderr = b""
        return self.stdout, self.stderr

    async def wait(self):
        return self.returncode

    def kill(self):
        pass


def setup_mock_subprocess(monkeypatch):
    """Set up mock subprocess to avoid interactive shell warnings"""

    async def mock_create_subprocess_shell(
        cmd,
        stdin=None,
        stdout=None,
        stderr=None,
        env=None,
        cwd=None,
        preexec_fn=None,
        start_new_session=None,
    ):
        # Return appropriate output based on command
        if "echo" in cmd:
            return MockProcess(stdout=b"hello world\n", stderr=b"", returncode=0)
        elif "pwd" in cmd:
            return MockProcess(stdout=cwd.encode() + b"\n", stderr=b"", returncode=0)
        elif "cat" in cmd:
            return MockProcess(
                stdout=None, stderr=b"", returncode=0
            )  # Will echo back stdin
        elif "ps" in cmd:
            return MockProcess(stdout=b"bash\n", stderr=b"", returncode=0)
        elif "env" in cmd:
            return MockProcess(stdout=b"TEST_ENV=value\n", stderr=b"", returncode=0)
        elif "sleep" in cmd:
            return MockProcess(stdout=b"", stderr=b"", returncode=0)
        elif "ls" in cmd and "/nonexistent/directory" in cmd:
            return MockProcess(
                stdout=b"",
                stderr=b"ls: cannot access '/nonexistent/directory': No such file or directory\n",
                returncode=2,
            )
        else:
            return MockProcess(stdout=b"", stderr=b"", returncode=0)

    monkeypatch.setattr(
        asyncio, "create_subprocess_shell", mock_create_subprocess_shell
    )


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        # Return the real path to handle macOS /private/tmp symlink
        yield os.path.realpath(tmpdirname)


@pytest.fixture
def execute_tool_handler():
    """Create an instance of ExecuteToolHandler for testing"""
    return ExecuteToolHandler()


@pytest.mark.asyncio
async def test_tool_definition(execute_tool_handler):
    """测试工具定义信息是否正确"""
    tool_def = execute_tool_handler.get_tool_def()
    
    assert isinstance(tool_def, Tool)
    assert tool_def.name == "shell_execute"
    assert "Execute a shell command" in tool_def.description
    assert tool_def.inputSchema["type"] == "object"
    assert "command" in tool_def.inputSchema["properties"]
    assert "directory" in tool_def.inputSchema["properties"]
    assert "stdin" in tool_def.inputSchema["properties"]
    assert "timeout" in tool_def.inputSchema["properties"]
    assert "encoding" in tool_def.inputSchema["properties"]
    assert "command" in tool_def.inputSchema["required"]
    assert "directory" in tool_def.inputSchema["required"]


@pytest.mark.asyncio
async def test_validate_arguments():
    """测试参数验证"""
    # 测试有效参数
    valid_args = {
        "command": ["echo", "hello"],
        "directory": "/tmp",
        "stdin": "input",
        "timeout": 10,
        "encoding": "utf-8"
    }
    model = ShellExecuteArgs.model_validate(valid_args)
    assert model.command == ["echo", "hello"]
    assert model.directory == "/tmp"
    assert model.stdin == "input"
    assert model.timeout == 10
    assert model.encoding == "utf-8"
    
    # 测试缺少必要参数
    with pytest.raises(Exception):
        ShellExecuteArgs.model_validate({"command": ["echo"]})
    
    with pytest.raises(Exception):
        ShellExecuteArgs.model_validate({"directory": "/tmp"})
    
    # 测试类型错误
    with pytest.raises(Exception):
        ShellExecuteArgs.model_validate({"command": "echo", "directory": "/tmp"})
    
    # 测试timeout范围
    with pytest.raises(Exception):
        ShellExecuteArgs.model_validate({
            "command": ["echo"],
            "directory": "/tmp",
            "timeout": -1  # 负数超时是无效的
        })


@pytest.mark.asyncio
async def test_run_tool_with_valid_command(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试执行有效命令"""
    setup_mock_subprocess(monkeypatch)
    monkeypatch.setenv("ALLOW_COMMANDS", "echo")
    
    result = await execute_tool_handler.run_tool({
        "command": ["echo", "hello world"],
        "directory": temp_test_dir
    })
    
    assert len(result) >= 1
    assert isinstance(result[0], TextContent)
    assert result[0].type == "text"
    # 检查退出状态
    assert any("exit with 0" in content.text for content in result)
    # 检查输出内容
    assert any("hello world" in content.text for content in result)


@pytest.mark.asyncio
async def test_run_tool_with_stdin(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试使用标准输入的命令执行"""
    setup_mock_subprocess(monkeypatch)
    monkeypatch.setenv("ALLOW_COMMANDS", "cat")
    
    result = await execute_tool_handler.run_tool({
        "command": ["cat"],
        "directory": temp_test_dir,
        "stdin": "test input"
    })
    
    assert len(result) >= 1
    assert isinstance(result[0], TextContent)
    assert any("test input" in content.text for content in result)


@pytest.mark.asyncio
async def test_run_tool_with_timeout(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试命令执行超时"""
    monkeypatch.setenv("ALLOW_COMMANDS", "sleep")
    
    with pytest.raises(ValueError) as excinfo:
        await execute_tool_handler.run_tool({
            "command": ["sleep", "2"],
            "directory": temp_test_dir,
            "timeout": 0  # 设置为0会立即超时
        })
    
    assert "Command execution timed out" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_tool_with_error(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试执行错误的命令"""
    monkeypatch.setenv("ALLOW_COMMANDS", "echo")
    
    with pytest.raises(ValueError) as excinfo:
        await execute_tool_handler.run_tool({
            "command": ["invalid_command"],
            "directory": temp_test_dir
        })
    
    assert "Command not allowed: invalid_command" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_tool_with_empty_command(execute_tool_handler, temp_test_dir):
    """测试空命令"""
    with pytest.raises(ValueError) as excinfo:
        await execute_tool_handler.run_tool({
            "command": [],
            "directory": temp_test_dir
        })
    
    assert "No command provided" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_tool_with_stderr(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试执行产生标准错误的命令"""
    setup_mock_subprocess(monkeypatch)
    monkeypatch.setenv("ALLOW_COMMANDS", "ls")
    
    result = await execute_tool_handler.run_tool({
        "command": ["ls", "/nonexistent/directory"],
        "directory": temp_test_dir
    })
    
    assert len(result) >= 1
    # 检查是否包含标准错误输出
    assert any("stderr" in content.text and "No such file or directory" in content.text 
              for content in result)


@pytest.mark.asyncio
async def test_run_tool_with_nonexistent_directory(execute_tool_handler, monkeypatch):
    """测试在不存在的目录执行命令"""
    monkeypatch.setenv("ALLOW_COMMANDS", "ls")
    nonexistent_dir = '/nonexistent/directory' if os.name != 'nt' else 'Z:\\nonexistent\\directory'
    
    with pytest.raises(ValueError) as excinfo:
        await execute_tool_handler.run_tool({
            "command": ["ls"],
            "directory": nonexistent_dir
        })
    
    assert f"Directory does not exist: {nonexistent_dir}" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_tool_with_encoding(execute_tool_handler, temp_test_dir, monkeypatch):
    """测试指定编码执行命令"""
    setup_mock_subprocess(monkeypatch)
    monkeypatch.setenv("ALLOW_COMMANDS", "echo")
    
    result = await execute_tool_handler.run_tool({
        "command": ["echo", "你好"],
        "directory": temp_test_dir,
        "encoding": "utf-8"
    })
    
    assert len(result) >= 1
    assert any("exit with 0" in content.text for content in result)
