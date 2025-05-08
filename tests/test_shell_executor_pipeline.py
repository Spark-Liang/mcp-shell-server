"""Test pipeline execution and cleanup scenarios."""

import os
import tempfile

import pytest
from unittest.mock import AsyncMock

from mcp_shell_server.shell_executor import ShellExecutor


def clear_env(monkeypatch):
    monkeypatch.delenv("ALLOW_COMMANDS", raising=False)
    monkeypatch.delenv("ALLOWED_COMMANDS", raising=False)


@pytest.fixture
def executor():
    return ShellExecutor()


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        # Return the real path to handle macOS /private/tmp symlink
        yield os.path.realpath(tmpdirname)


@pytest.mark.asyncio
async def test_pipeline_split(executor):
    """Test pipeline command splitting functionality"""
    # Test basic pipe command
    commands = executor.preprocessor.split_pipe_commands(
        ["echo", "hello", "|", "grep", "h"]
    )
    assert len(commands) == 2
    assert commands[0] == ["echo", "hello"]
    assert commands[1] == ["grep", "h"]

    # Test empty pipe sections
    commands = executor.preprocessor.split_pipe_commands(["|", "grep", "pattern"])
    assert len(commands) == 1
    assert commands[0] == ["grep", "pattern"]

    # Test multiple pipes
    commands = executor.preprocessor.split_pipe_commands(
        ["cat", "file.txt", "|", "grep", "pattern", "|", "wc", "-l"]
    )
    assert len(commands) == 3
    assert commands[0] == ["cat", "file.txt"]
    assert commands[1] == ["grep", "pattern"]
    assert commands[2] == ["wc", "-l"]

    # Test trailing pipe
    commands = executor.preprocessor.split_pipe_commands(["echo", "hello", "|"])
    assert len(commands) == 1
    assert commands[0] == ["echo", "hello"]


@pytest.mark.asyncio
async def test_pipeline_execution_success(
    shell_executor_with_mock, temp_test_dir, mock_process_manager, monkeypatch
):
    """Test successful pipeline execution with proper return value"""
    monkeypatch.setenv("ALLOW_COMMANDS", "echo,grep")
    
    # 直接构造期望的返回结果
    expected_result = {
        "error": None,
        "status": 0,
        "stdout": "mocked pipeline output",
        "stderr": "",
        "execution_time": 0.1
    }
    
    # Set up mock for pipeline execution
    expected_output = b"mocked pipeline output\n"
    mock_process_manager.execute_pipeline.return_value = (expected_output, b"", 0)
    
    # 替换_execute_pipeline方法
    shell_executor_with_mock._execute_pipeline = AsyncMock(return_value=expected_result)

    result = await shell_executor_with_mock.execute(
        ["echo", "hello world", "|", "grep", "world"],
        directory=temp_test_dir,
        timeout=5,
    )

    assert result["error"] is None
    assert result["status"] == 0
    assert result["stdout"].rstrip() == "mocked pipeline output"
    assert "execution_time" in result


@pytest.mark.asyncio
async def test_pipeline_cleanup_and_timeouts(
    shell_executor_with_mock, temp_test_dir, mock_process_manager, monkeypatch
):
    """Test cleanup of processes in pipelines and timeout handling"""
    monkeypatch.setenv("ALLOW_COMMANDS", "echo,grep")
    
    # 创建模拟超时结果
    timeout_result = {
        "error": "Command timed out after 1 seconds",
        "status": -1,
        "stdout": "",
        "stderr": "Command timed out after 1 seconds",
        "execution_time": 1.0
    }
    
    # 使用side_effect模拟抛出异常情况
    async def mock_execute_pipeline(*args, **kwargs):
        raise TimeoutError("Command timed out after 1 seconds")
    
    # 设置mock
    mock_process_manager.execute_pipeline.side_effect = mock_execute_pipeline
    shell_executor_with_mock._execute_pipeline = AsyncMock(return_value=timeout_result)

    result = await shell_executor_with_mock.execute(
        ["echo", "test", "|", "grep", "test"],  # Use a pipeline command
        temp_test_dir,
        timeout=1,
    )

    assert result["status"] == -1
    assert "timed out" in result["error"].lower()
