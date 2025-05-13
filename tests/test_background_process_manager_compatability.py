"""Tests for the ProcessManager class."""

import asyncio
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_shell_server.background_process_manager import BackgroundProcessManager


def create_mock_process():
    """Create a mock process with all required attributes."""
    process = MagicMock()
    process.pid = random.randint(10000, 99999)
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"output", b"error"))
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


@pytest.fixture
def process_manager():
    """Fixture for ProcessManager instance."""
    return BackgroundProcessManager()


@pytest.mark.asyncio
async def test_create_process(process_manager):
    """Test creating a process with basic parameters."""
    mock_proc = create_mock_process()
    with patch(
        "mcp_shell_server.background_process_manager.asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ) as mock_create:
        process = await process_manager.create_process(
            "echo 'test'",
            directory="/tmp",
            stdin="input",
        )

        assert process.pid == mock_proc.pid
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_timeout_success(process_manager):
    """Test executing a process with successful completion."""
    mock_proc = create_mock_process()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"output", b"error")

    stdout, stderr = await process_manager.execute_with_timeout(
        mock_proc,
        stdin=b"input",
        timeout=10,
    )

    assert stdout == b"output"
    assert stderr == b"error"
    mock_proc.communicate.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_timeout_timeout(process_manager):
    """Test executing a process that times out."""
    mock_proc = create_mock_process()
    exc = asyncio.TimeoutError("Process timed out")
    mock_proc.communicate.side_effect = exc
    mock_proc.returncode = None  # プロセスがまだ実行中の状態をシミュレート

    # プロセスの終了状態をシミュレート
    async def set_returncode():
        mock_proc.returncode = -15  # SIGTERM

    mock_proc.wait.side_effect = set_returncode

    with pytest.raises(TimeoutError):
        await process_manager.execute_with_timeout(
            mock_proc,
            timeout=1,
        )

    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_execute_pipeline_success(process_manager):
    """Test executing a pipeline of commands successfully."""
    mock_proc1 = create_mock_process()
    mock_proc1.communicate.return_value = (b"output1", b"")
    mock_proc1.returncode = 0
    mock_proc1.wait = AsyncMock(return_value=0)
    
    mock_proc2 = create_mock_process()
    mock_proc2.communicate.return_value = (b"final output", b"")
    mock_proc2.returncode = 0
    mock_proc2.wait = AsyncMock(return_value=0)
    
    # 创建模拟的 BackgroundProcess 对象
    mock_bg_proc1 = MagicMock()
    mock_bg_proc1.process = mock_proc1
    mock_bg_proc1.returncode = 0
    mock_bg_proc1.process_id = "mock1"
    mock_bg_proc1.wait = AsyncMock(return_value=0)
    mock_bg_proc1.is_running = MagicMock(return_value=False)
    mock_bg_proc1.encoding = "utf-8"
    
    mock_bg_proc2 = MagicMock()
    mock_bg_proc2.process = mock_proc2
    mock_bg_proc2.returncode = 0
    mock_bg_proc2.process_id = "mock2"
    mock_bg_proc2.wait = AsyncMock(return_value=0)
    mock_bg_proc2.is_running = MagicMock(return_value=False)
    mock_bg_proc2.encoding = "utf-8"
    
    # 直接模拟 create_process 方法
    with patch.object(
        process_manager, 
        "create_process",
        new_callable=AsyncMock,
        side_effect=[mock_bg_proc1, mock_bg_proc2]
    ):
        # 直接模拟 execute_with_timeout 方法
        with patch.object(
            process_manager, 
            "execute_with_timeout",
            new_callable=AsyncMock,
            side_effect=[
                (b"output1", b""),
                (b"final output", b"")
            ]
        ):
            stdout, stderr, return_code = await process_manager.execute_pipeline(
                ["echo 'test'", "grep test"],
                directory="/tmp",
                timeout=10,
            )
            
            assert stdout == b"final output"
            assert stderr == b""
            assert return_code == 0


@pytest.mark.asyncio
async def test_execute_pipeline_with_error(process_manager):
    """Test executing a pipeline where a command fails."""
    mock_proc = create_mock_process()
    mock_proc.communicate.return_value = (b"", b"error message")
    mock_proc.returncode = 1

    create_process_mock = AsyncMock(return_value=mock_proc)

    with patch.object(process_manager, "create_process", create_process_mock):
        with pytest.raises(ValueError, match="error message"):
            await process_manager.execute_pipeline(
                ["invalid_command"],
                directory="/tmp",
            )


@pytest.mark.asyncio
async def test_cleanup_processes(process_manager):
    """Test cleaning up processes."""
    # Create mock processes with different states
    running_proc = create_mock_process()
    running_proc.returncode = None

    completed_proc = create_mock_process()
    completed_proc.returncode = 0

    # Execute cleanup
    await process_manager.cleanup_processes([running_proc, completed_proc])

    # Verify running process was killed and waited for
    running_proc.kill.assert_called_once()
    running_proc.wait.assert_awaited_once()

    # Verify completed process was not killed or waited for
    completed_proc.kill.assert_not_called()
    completed_proc.wait.assert_not_called()


@pytest.mark.asyncio
async def test_create_process_with_error(process_manager):
    """Test creating a process that fails to start."""
    with patch(
        "asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
        side_effect=OSError("Failed to create process"),
    ):
        with pytest.raises(ValueError, match="Failed to create process"):
            await process_manager.create_process("invalid command", directory="/tmp")


@pytest.mark.asyncio
async def test_execute_pipeline_empty_commands(process_manager):
    """Test executing a pipeline with no commands."""
    with pytest.raises(ValueError, match="No commands provided"):
        await process_manager.execute_pipeline([], directory="/tmp")


@pytest.mark.asyncio
async def test_execute_pipeline_timeout(process_manager):
    """Test executing a pipeline that times out."""
    # 创建能正确响应异步调用的 Mock 对象
    mock_proc = create_mock_process()
    # 确保 communicate 是 AsyncMock 并抛出 TimeoutError
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError("Process timed out"))
    mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    
    # 修改测试策略，直接模拟 execute_with_timeout 抛出超时异常
    with patch.object(
        process_manager, 
        "execute_with_timeout",
        AsyncMock(side_effect=TimeoutError("进程执行超时"))
    ):
        with patch.object(
            process_manager,
            "create_process",
            AsyncMock(return_value=mock_proc)
        ):
            # 匹配正确的错误消息
            with pytest.raises(TimeoutError, match="进程执行超时"):
                await process_manager.execute_pipeline(
                    ["sleep 10"],
                    directory="/tmp",
                    timeout=1,
                )
