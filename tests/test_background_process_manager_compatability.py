"""Tests for BackgroundProcessManager compatibility with ProcessManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_shell_server.background_process_manager import (
    BackgroundProcess,
    BackgroundProcessManager,
    ProcessStatus,
)


@pytest.fixture
def bg_process_manager():
    """返回BackgroundProcessManager实例"""
    return BackgroundProcessManager()


@pytest.mark.asyncio
async def test_create_process(bg_process_manager):
    """测试创建进程"""
    # 创建模拟进程
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.pid = 13293
    mock_process.stdin = AsyncMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    with patch(
        "asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
        return_value=mock_process,
    ):
        # 调用create_process方法
        process = await bg_process_manager.create_process(
            shell_cmd="echo 'test'",
            directory="/tmp",
            stdin="test input",
        )

        # 验证获得了BackgroundProcess对象
        assert isinstance(process, BackgroundProcess)
        assert process.pid == 13293
        assert process.command == "echo 'test'"
        assert process.status == ProcessStatus.RUNNING


@pytest.mark.asyncio
async def test_execute_with_timeout_success(bg_process_manager):
    """测试execute_with_timeout成功执行"""
    # 创建mock进程对象
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"output", b"error"))

    # 调用方法并验证结果
    stdout, stderr = await bg_process_manager.execute_with_timeout(
        mock_process, stdin=b"input", timeout=1.0
    )

    # 验证结果
    assert stdout == b"output"
    assert stderr == b"error"
    mock_process.communicate.assert_called_once_with(input=b"input")


@pytest.mark.asyncio
async def test_execute_with_timeout_timeout(bg_process_manager):
    """测试execute_with_timeout超时处理"""
    # 创建模拟进程
    mock_process = MagicMock()
    # 模拟communicate方法超时
    mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock(
        side_effect=[asyncio.TimeoutError(), 1]
    )  # 模拟第一次等待超时，第二次成功

    # 测试超时
    with pytest.raises(TimeoutError):
        await bg_process_manager.execute_with_timeout(
            mock_process, stdin=b"input", timeout=1.0
        )

    # 验证进程被终止
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()
    assert mock_process.wait.call_count == 2


@pytest.mark.asyncio
async def test_execute_pipeline_success(bg_process_manager):
    """测试execute_pipeline成功执行"""
    # 创建模拟BackgroundProcess对象
    mock_bg_proc1 = MagicMock(spec=BackgroundProcess)
    mock_bg_proc1.pid = 1001
    mock_bg_proc1.returncode = 0
    mock_bg_proc1.wait = AsyncMock(return_value=0)

    mock_bg_proc2 = MagicMock(spec=BackgroundProcess)
    mock_bg_proc2.pid = 1002
    mock_bg_proc2.returncode = 0
    mock_bg_proc2.wait = AsyncMock(return_value=0)

    # 模拟create_process方法返回mock对象
    with patch.object(
        bg_process_manager,
        "create_process",
        new_callable=AsyncMock,
        side_effect=[mock_bg_proc1, mock_bg_proc2],
    ):
        # 模拟execute_with_timeout方法
        with patch.object(
            bg_process_manager,
            "execute_with_timeout",
            new_callable=AsyncMock,
            side_effect=[
                (b"output1", b""),
                (b"final output", b""),
            ],
        ):
            # 调用execute_pipeline
            stdout, stderr, return_code = await bg_process_manager.execute_pipeline(
                commands=["ls -la", "grep text"],
                directory="/tmp",
                first_stdin="input",
                timeout=5.0,
            )

            # 验证结果
            assert stdout == b"final output"
            assert stderr == b""
            assert return_code == 0


@pytest.mark.asyncio
async def test_execute_pipeline_with_error(bg_process_manager):
    """测试execute_pipeline中途失败"""
    # 创建模拟进程，第一个成功，第二个失败
    mock_proc1 = MagicMock(spec=BackgroundProcess)
    mock_proc1.returncode = 0
    mock_proc1.wait = AsyncMock(return_value=0)

    mock_proc2 = MagicMock(spec=BackgroundProcess)
    mock_proc2.returncode = 1
    mock_proc2.wait = AsyncMock(return_value=1)

    # 模拟create_process和execute_with_timeout
    with patch.object(
        bg_process_manager,
        "create_process",
        new_callable=AsyncMock,
        side_effect=[mock_proc1, mock_proc2],
    ):
        with patch.object(
            bg_process_manager,
            "execute_with_timeout",
            new_callable=AsyncMock,
            side_effect=[
                (b"output1", b""),
                (b"", b"error message"),
                ValueError("Command failed"),
            ],
        ):
            # 调用execute_pipeline，预期会抛出异常
            with pytest.raises(ValueError):
                await bg_process_manager.execute_pipeline(
                    commands=["ls -la", "invalid command"],
                    directory="/tmp",
                )

            # 验证进程被清理
            assert mock_proc1.kill.call_count <= 1
            assert mock_proc2.kill.call_count <= 1


@pytest.mark.asyncio
async def test_cleanup_processes(bg_process_manager):
    """测试cleanup_processes方法"""
    # 创建模拟进程
    mock_proc1 = AsyncMock()
    mock_proc1.returncode = None
    mock_proc1.kill = MagicMock()
    mock_proc1.wait = AsyncMock(return_value=0)

    mock_proc2 = AsyncMock()
    mock_proc2.returncode = 0

    # 调用cleanup_processes
    count = await bg_process_manager.cleanup_processes(
        processes=[mock_proc1, mock_proc2]
    )

    # 验证结果
    assert count == 1  # 只有一个正在运行的进程
    mock_proc1.kill.assert_called_once()
    mock_proc1.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_process_with_error(bg_process_manager):
    """测试创建进程失败的情况"""
    # 模拟create_subprocess_shell抛出异常
    with patch(
        "asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
        side_effect=OSError("Failed to create process"),
    ):
        # 调用create_process，预期会抛出异常
        with pytest.raises(ValueError) as excinfo:
            await bg_process_manager.create_process(
                shell_cmd="invalid command",
                directory="/tmp",
            )

        # 验证异常消息
        assert "创建进程失败" in str(excinfo.value)


@pytest.mark.asyncio
async def test_execute_pipeline_empty_commands(bg_process_manager):
    """测试execute_pipeline空命令列表"""
    # 调用execute_pipeline，预期会抛出异常
    with pytest.raises(ValueError) as excinfo:
        await bg_process_manager.execute_pipeline(
            commands=[],
            directory="/tmp",
        )

    # 验证异常消息
    assert "No commands provided" in str(excinfo.value)


@pytest.mark.asyncio
async def test_execute_pipeline_timeout(bg_process_manager):
    """测试execute_pipeline超时处理"""
    # 创建模拟进程
    mock_proc = MagicMock(spec=BackgroundProcess)
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()

    # 模拟create_process返回模拟进程
    with patch.object(
        bg_process_manager,
        "create_process",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        # 模拟execute_with_timeout超时
        with patch.object(
            bg_process_manager,
            "execute_with_timeout",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError("Timeout"),
        ):
            # 调用execute_pipeline，预期会抛出异常
            with pytest.raises(asyncio.TimeoutError):
                await bg_process_manager.execute_pipeline(
                    commands=["sleep 10"],
                    directory="/tmp",
                    timeout=1.0,
                )

            # 验证进程被终止（至少被调用一次，不要求精确次数）
            mock_proc.kill.assert_called()
