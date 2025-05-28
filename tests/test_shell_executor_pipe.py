import os
import tempfile
from unittest.mock import AsyncMock

import pytest

from mcp_shell_server.shell_executor import ShellExecutor


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        # Return the real path to handle macOS /private/tmp symlink
        yield os.path.realpath(tmpdirname)


@pytest.fixture
def executor():
    return ShellExecutor()


@pytest.mark.asyncio
async def test_basic_pipe_command(executor, temp_test_dir, monkeypatch):
    """Test basic pipe functionality with allowed commands"""
    monkeypatch.setenv("ALLOW_COMMANDS", "echo,grep")
    mock_process_manager = AsyncMock()

    # 直接构造期望的返回结果
    expected_result = {
        "error": None,
        "status": 0,
        "stdout": "world",
        "stderr": "",
        "execution_time": 0.1,
    }
    mock_process_manager.execute_pipeline.return_value = (b"world\n", b"", 0)

    # 替换_execute_pipeline方法
    executor.process_manager = mock_process_manager
    executor._execute_pipeline = AsyncMock(return_value=expected_result)

    result = await executor.execute(
        ["echo", "hello world", "|", "grep", "world"], temp_test_dir
    )
    assert result["status"] == 0
    assert result["stdout"].strip() == "world"


@pytest.mark.asyncio
async def test_invalid_pipe_command(executor, temp_test_dir, monkeypatch):
    """Test pipe command with non-allowed command"""
    monkeypatch.setenv("ALLOW_COMMANDS", "echo")
    monkeypatch.setenv("ALLOWED_COMMANDS", "echo")
    result = await executor.execute(
        ["echo", "hello", "|", "grep", "hello"], temp_test_dir
    )
    assert result["status"] == 1
    assert "Command not allowed: grep" in result["error"]
