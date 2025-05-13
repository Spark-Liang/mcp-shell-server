"""Tests for the BackgroundProcessManager class."""

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_shell_server.background_process_manager import (
    BackgroundProcess,
    BackgroundProcessManager,
    ProcessStatus,
)
from mcp_shell_server.interfaces import LogEntry


@pytest.fixture
def bg_process_manager():
    """提供BackgroundProcessManager实例"""
    return BackgroundProcessManager()


@pytest.fixture
async def cleanup_bg_processes(bg_process_manager):
    """测试后清理所有后台进程"""
    yield
    await bg_process_manager.cleanup_all()


@pytest.mark.asyncio
async def test_create_process(bg_process_manager, cleanup_bg_processes):
    """测试创建后台进程"""
    # 模拟进程创建
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 12345  # 设置模拟进程的pid属性为整数
    mock_proc.communicate = AsyncMock(return_value=(b"output", b"error"))
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.close = MagicMock()
    
    with patch(
        "asyncio.create_subprocess_shell", 
        new_callable=AsyncMock, 
        return_value=mock_proc
    ) as mock_create, patch.object(
        bg_process_manager, "_monitor_process", AsyncMock()
    ):
        
        # 创建一个后台进程
        temp_dir = tempfile.gettempdir()
        bg_process = await bg_process_manager.create_process(
            shell_cmd="echo test",
            directory=temp_dir,
            description="Test background process",
            labels=["test"],
            stdin="input data",
        )
        
        # 验证进程创建
        assert bg_process.pid is not None
        assert isinstance(bg_process.pid, int)  # 确认pid是整数类型
        assert bg_process.command == "echo test"
        assert bg_process.directory == temp_dir
        assert bg_process.description == "Test background process"
        assert bg_process.labels == ["test"]
        assert bg_process.status == ProcessStatus.RUNNING
        assert bg_process.process.pid == mock_proc.pid
        
        # 验证stdin写入
        mock_proc.stdin.write.assert_called_once()
        mock_proc.stdin.drain.assert_awaited_once()
        mock_proc.stdin.close.assert_called_once()
        
        # 验证日志文件创建
        assert os.path.exists(bg_process.log_dir)
        assert os.path.isfile(bg_process.stdout_log)
        assert os.path.isfile(bg_process.stderr_log)
        

@pytest.mark.asyncio
async def test_start_process(bg_process_manager, cleanup_bg_processes):
    """测试启动后台进程并返回ID"""
    # 创建临时目录用于测试
    temp_dir = tempfile.gettempdir()
    
    # 模拟进程创建
    create_process_mock = AsyncMock()
    mock_bg_process = AsyncMock(spec=BackgroundProcess)
    mock_bg_process.pid = 12345  # 使用整数pid代替字符串process_id
    create_process_mock.return_value = mock_bg_process
    
    with patch.object(bg_process_manager, "create_process", create_process_mock):
        process_pid = await bg_process_manager.start_process(
            shell_cmd="echo test",
            directory=temp_dir,
            description="Test process",
            labels=["test", "example"],
        )
        
        # 验证返回的进程PID
        assert process_pid == 12345
        
        # 验证create_process被正确调用
        create_process_mock.assert_awaited_once_with(
            shell_cmd="echo test",
            directory=temp_dir,
            description="Test process",
            labels=["test", "example"],
            stdin=None,
            envs=None,
            encoding=None,
            timeout=None,
        )


@pytest.mark.asyncio
async def test_get_process_output(bg_process_manager, cleanup_bg_processes):
    """测试获取进程输出"""
    # 创建带模拟输出的后台进程
    pid = 12345  # 使用整数pid代替字符串process_id

    # 创建模拟后台进程
    bg_process = MagicMock()
    bg_process.pid = pid
    bg_process.status = ProcessStatus.RUNNING

    # 获取当前时间用于测试
    now = datetime.now()

    # 模拟输出获取方法
    output_data = [
        LogEntry(timestamp=now, text="line 1"),
        LogEntry(timestamp=now, text="line 2"),
    ]
    error_data = [
        LogEntry(timestamp=now, text="error 1"),
    ]

    bg_process.get_output.return_value = output_data
    bg_process.get_error.return_value = error_data

    # 添加到进程字典
    bg_process_manager._processes[pid] = bg_process

    # 测试获取标准输出
    stdout = await bg_process_manager.get_process_output(pid)
    assert stdout == output_data
    bg_process.get_output.assert_called_once_with(tail=None, since=None, until=None)

    # 测试获取错误输出
    stderr = await bg_process_manager.get_process_output(pid, error=True)
    assert stderr == error_data
    bg_process.get_error.assert_called_once_with(tail=None, since=None, until=None)

    # 测试带参数获取
    bg_process.get_output.reset_mock()

    since_time = (datetime.now() - timedelta(hours=1)).isoformat()
    await bg_process_manager.get_process_output(pid, tail=10, since_time=since_time)

    # 验证参数传递正确
    call_args = bg_process.get_output.call_args[1]
    assert call_args["tail"] == 10
    assert isinstance(call_args["since"], datetime)  # 验证since_time被转换为datetime
    assert call_args["until"] is None  # 验证until为None

    # 测试获取不存在的进程输出
    nonexistent_pid = 99999
    with pytest.raises(ValueError, match=f"没有找到PID为 {nonexistent_pid} 的进程"):
        await bg_process_manager.get_process_output(nonexistent_pid)


@pytest.mark.asyncio
async def test_cleanup_all(bg_process_manager):
    """测试清理所有进程"""
    # 创建模拟进程
    process1 = MagicMock()
    process1.is_running.return_value = True
    process1.process = MagicMock()
    process1.process.returncode = None
    process1.cleanup = MagicMock()
    
    process2 = MagicMock()
    process2.is_running.return_value = False
    process2.cleanup = MagicMock()
    
    # 添加到进程管理器
    bg_process_manager._processes = {
        1001: process1,
        1002: process2
    }
    
    # 清理所有进程
    with patch.object(bg_process_manager, "stop_process", AsyncMock()) as mock_stop:
        await bg_process_manager.cleanup_all()
        
        # 验证运行中的进程被停止
        mock_stop.assert_called_once_with(1001, force=True)
        
        # 验证清理后进程字典为空
        assert len(bg_process_manager._processes) == 0
        
        # 验证清理方法被调用
        process1.cleanup.assert_called_once()
        process2.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_processes(bg_process_manager):
    """测试清理进程功能，按标签和状态过滤"""
    # 创建模拟进程
    process1 = MagicMock()
    process1.pid = 1001
    process1.labels = ["test", "web"]
    process1.status = ProcessStatus.RUNNING
    process1.is_running.return_value = True
    
    process2 = MagicMock()
    process2.pid = 1002
    process2.labels = ["test", "db"]
    process2.status = ProcessStatus.COMPLETED
    process2.is_running.return_value = False
    
    process3 = MagicMock()
    process3.pid = 1003
    process3.labels = ["db"]
    process3.status = ProcessStatus.FAILED
    process3.is_running.return_value = False
    
    # 准备清理方法的mock
    with patch.object(bg_process_manager, "cleanup_process", AsyncMock()) as mock_cleanup:
        # 测试按状态过滤 - 应该清理 COMPLETED 状态的进程
        # 重置进程字典
        bg_process_manager._processes = {
            1001: process1,
            1002: process2,
            1003: process3
        }
        count = await bg_process_manager.cleanup_processes(status=ProcessStatus.COMPLETED)
        assert count == 1
        mock_cleanup.assert_called_once_with(1002)
        mock_cleanup.reset_mock()
        
        # 测试按标签过滤 - 应该清理标签为 "db" 的非运行状态进程
        # 重置进程字典
        bg_process_manager._processes = {
            1001: process1,
            1002: process2,
            1003: process3
        }
        count = await bg_process_manager.cleanup_processes(labels=["db"])
        assert count == 2  # proc2 和 proc3 都应该被清理
        assert mock_cleanup.call_count == 2
        mock_cleanup.reset_mock()
        
        # 测试不带过滤器 - 应该清理所有非运行状态的进程
        # 重置进程字典
        bg_process_manager._processes = {
            1001: process1,
            1002: process2,
            1003: process3
        }
        count = await bg_process_manager.cleanup_processes()
        assert count == 2  # proc2 和 proc3 都应该被清理
        assert mock_cleanup.call_count == 2


@pytest.mark.asyncio
async def test_follow_process_output(bg_process_manager):
    """测试实时跟踪进程输出"""
    pid = 54321  # 使用整数pid代替字符串process_id

    # 创建模拟后台进程
    bg_process = MagicMock()
    bg_process.pid = pid

    # 模拟is_running方法，前两次调用返回True，第三次返回False
    is_running_mock = MagicMock()
    is_running_values = [True, True, False]
    is_running_mock.side_effect = is_running_values
    bg_process.is_running = is_running_mock

    # 模拟时间戳
    now = datetime.now()

    # 模拟初始输出
    initial_output = [
        LogEntry(timestamp=now, text="初始输出 1"),
    ]

    # 模拟后续输出
    new_output1 = [
        LogEntry(timestamp=now + timedelta(seconds=1), text="新输出 1"),
    ]

    new_output2 = [
        LogEntry(timestamp=now + timedelta(seconds=2), text="新输出 2"),
    ]

    # 设置get_output返回值序列
    bg_process.get_output = MagicMock()
    bg_process.get_output.side_effect = [
        initial_output,  # 初始调用
        new_output1,     # 第一次轮询
        new_output2,     # 第二次轮询
    ]

    # 添加到进程字典
    bg_process_manager._processes[pid] = bg_process

    # 使用较短的轮询间隔加速测试
    poll_interval = 0.01

    # 跟踪输出
    collected_outputs = []
    async for output in bg_process_manager.follow_process_output(
        pid, poll_interval=poll_interval
    ):
        collected_outputs.append(output)
        if len(collected_outputs) >= 4:  # 防止无限循环
            break

    # 验证收集到的输出
    expected_outputs = initial_output + new_output1 + new_output2
    assert collected_outputs == expected_outputs[:len(collected_outputs)]

    # 验证is_running被调用了正确的次数
    assert bg_process.is_running.call_count <= 3


@pytest.mark.asyncio
async def test_process_timeout(bg_process_manager, cleanup_bg_processes):
    """测试进程超时处理"""
    # 创建会超时的进程的模拟
    mock_proc = MagicMock()
    mock_proc.returncode = None
    
    # 模拟 wait 方法，实际并不会返回（一直等待）
    wait_future = asyncio.Future()
    mock_proc.wait = MagicMock(return_value=wait_future)  # 永远不会完成的 Future
    
    # 模拟 stdout 和 stderr
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()
    
    # 使用普通 MagicMock 而非 AsyncMock 来避免协程警告
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    
    # 模拟 iscoroutinefunction 返回 False 避免尝试 await
    with patch(
        "asyncio.create_subprocess_shell", 
        new_callable=AsyncMock, 
        return_value=mock_proc
    ), patch(
        "asyncio.wait_for", 
        side_effect=asyncio.TimeoutError  # 模拟超时
    ), patch(
        "asyncio.iscoroutinefunction",
        return_value=False  # 使方法被视为非协程
    ), patch.object(
        BackgroundProcess, 
        "add_error", 
        MagicMock()
    ) as add_error_mock:
        # 创建一个有超时设置的后台进程
        proc_id = await bg_process_manager.start_process(
            shell_cmd="sleep 10",  # 不会实际执行
            directory=tempfile.gettempdir(),
            description="超时测试进程",
            timeout=1  # 1秒超时
        )
        
        # 获取进程对象
        bg_process = await bg_process_manager.get_process(proc_id)
        
        # 等待一点时间让监控任务执行
        await asyncio.sleep(0.1)
        
        # 手动运行监控过程（由于我们模拟了依赖）
        monitor_task = bg_process.monitor_task
        if monitor_task and not monitor_task.done():
            # 取消任务并等待它完成
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
        # 验证进程状态
        assert bg_process.status == ProcessStatus.TERMINATED
        assert bg_process.exit_code == -1  # 超时的特殊退出码
        
        # 验证错误消息被添加
        add_error_mock.assert_called_once()
        error_msg = add_error_mock.call_args[0][0]
        assert "超时" in error_msg
        
        # 验证终止方法被调用
        mock_proc.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_execute_pipeline(bg_process_manager, cleanup_bg_processes):
    """测试管道命令执行功能"""
    # 创建模拟进程
    mock_proc1 = MagicMock()
    mock_proc1.returncode = 0
    mock_proc1.communicate = AsyncMock(return_value=(b"output1", b""))
    mock_proc1.wait = AsyncMock(return_value=0)  # 确保 wait 是异步方法
    mock_proc1.stdout = MagicMock()
    mock_proc1.stderr = MagicMock()
    
    mock_proc2 = MagicMock()
    mock_proc2.returncode = 0
    mock_proc2.communicate = AsyncMock(return_value=(b"pipeline output", b""))
    mock_proc2.wait = AsyncMock(return_value=0)  # 确保 wait 是异步方法
    mock_proc2.stdout = MagicMock()
    mock_proc2.stderr = MagicMock()
    
    mock_proc3 = MagicMock()
    mock_proc3.returncode = 0
    mock_proc3.communicate = AsyncMock(return_value=(b"final output", b""))
    mock_proc3.wait = AsyncMock(return_value=0)  # 确保 wait 是异步方法
    mock_proc3.stdout = MagicMock()
    mock_proc3.stderr = MagicMock()
    
    # 准备测试命令
    commands = ["ls -la", "grep txt", "wc -l"]
    temp_dir = tempfile.gettempdir()
    
    # 完全模拟 BackgroundProcess 对象，避免使用实际的 create_process
    with patch.object(
        bg_process_manager, 
        "create_process",
        new_callable=AsyncMock, 
        side_effect=[
            # 返回模拟的 BackgroundProcess 对象
            AsyncMock(
                spec=BackgroundProcess, 
                process=mock_proc1, 
                status=ProcessStatus.RUNNING,
                returncode=0,
                pid=1001,
                wait=AsyncMock(return_value=0),
                is_running=MagicMock(return_value=False),
                encoding="utf-8"
            ),
            AsyncMock(
                spec=BackgroundProcess,
                process=mock_proc2,
                status=ProcessStatus.RUNNING,
                returncode=0,
                pid=1002,
                wait=AsyncMock(return_value=0),
                is_running=MagicMock(return_value=False),
                encoding="utf-8"
            ),
            AsyncMock(
                spec=BackgroundProcess,
                process=mock_proc3,
                status=ProcessStatus.RUNNING,
                returncode=0,
                pid=1003,
                wait=AsyncMock(return_value=0),
                is_running=MagicMock(return_value=False),
                encoding="utf-8"
            )
        ]
    ):
        # 模拟 execute_with_timeout 方法
        with patch.object(
            bg_process_manager, 
            "execute_with_timeout",
            new_callable=AsyncMock, 
            side_effect=[
                (b"output1", b""),
                (b"pipeline output", b""),
                (b"final output", b"")
            ]
        ):
            # 执行管道命令
            stdout, stderr, return_code = await bg_process_manager.execute_pipeline(
                commands=commands,
                directory=temp_dir,
                description="测试管道命令",
                labels=["test", "pipeline"],
                first_stdin="test input",
            )
            
            # 验证返回结果
            assert stdout == b"final output"
            assert stderr == b""
            assert return_code == 0
    
    # 测试空命令列表
    with pytest.raises(ValueError, match="No commands provided"):
        await bg_process_manager.execute_pipeline(
            commands=[],
            directory=temp_dir,
            description="空命令测试",
        )

@pytest.mark.asyncio
async def test_get_process_status_summary(bg_process_manager):
    """测试获取进程状态摘要"""
    # 创建各种状态的模拟进程
    proc1 = MagicMock()
    proc1.status = ProcessStatus.RUNNING
    
    proc2 = MagicMock()
    proc2.status = ProcessStatus.COMPLETED
    
    proc3 = MagicMock()
    proc3.status = ProcessStatus.COMPLETED
    
    proc4 = MagicMock()
    proc4.status = ProcessStatus.FAILED
    
    proc5 = MagicMock()
    proc5.status = ProcessStatus.TERMINATED
    
    # 添加到进程管理器
    bg_process_manager._processes = {
        1001: proc1,
        1002: proc2,
        1003: proc3,
        1004: proc4,
        1005: proc5
    }
    
    # 获取状态摘要
    summary = await bg_process_manager.get_process_status_summary()
    
    # 验证摘要内容
    assert summary["running"] == 1
    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["terminated"] == 1
    assert summary["error"] == 0  # 没有错误状态的进程
    
    # 清空进程字典
    bg_process_manager._processes.clear()
    
    # 验证空进程列表的摘要
    empty_summary = await bg_process_manager.get_process_status_summary()
    assert all(count == 0 for count in empty_summary.values())

@pytest.mark.asyncio
async def test_auto_cleanup_processes():
    """测试自动延迟清理进程的功能"""
    # 临时修改环境变量，设置较短的保留时间
    original_retention = os.environ.get('PROCESS_RETENTION_SECONDS')
    
    try:
        # 设置为1秒的保留时间
        os.environ['PROCESS_RETENTION_SECONDS'] = '1'
        
        # 创建临时工作目录
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建进程管理器
            manager = BackgroundProcessManager()
            
            # 手动创建已完成的进程对象
            process1 = BackgroundProcess(
                shell_cmd="echo test1",
                directory=temp_dir,
                description="Test process 1"
            )
            process1.pid = 10001
            process1.status = ProcessStatus.COMPLETED
            process1.end_time = datetime.now() - timedelta(seconds=5)  # 5秒前结束
            
            process2 = BackgroundProcess(
                shell_cmd="echo test2",
                directory=temp_dir,
                description="Test process 2"
            )
            process2.pid = 10002
            process2.status = ProcessStatus.COMPLETED
            process2.end_time = datetime.now()  # 刚刚结束
            
            # 模拟一个仍在运行的进程
            process3 = BackgroundProcess(
                shell_cmd="echo test3",
                directory=temp_dir,
                description="Test process 3"
            )
            process3.pid = 10003
            
            # 添加到进程管理器的字典中
            manager._processes[process1.pid] = process1
            manager._processes[process2.pid] = process2
            manager._processes[process3.pid] = process3
            
            # 为已完成的进程安排延迟清理
            manager.schedule_delayed_cleanup(process1.pid)
            manager.schedule_delayed_cleanup(process2.pid)
            
            # 验证清理任务已安排
            assert process1.cleanup_scheduled
            assert process2.cleanup_scheduled
            assert process1.cleanup_handle is not None
            assert process2.cleanup_handle is not None
            assert not process3.cleanup_scheduled  # 运行中的进程不应该安排清理
            
            # 等待延迟清理执行（等待比保留时间稍长一点）
            await asyncio.sleep(1.5)
            
            # 检查进程1是否已被清理
            assert process1.pid not in manager._processes
            
            # 确保进程3（运行中的进程）没有被清理
            assert process3.pid in manager._processes
            
            # 手动清理所有进程
            await manager.cleanup_all()
            
            # 验证所有进程都已被清理
            assert len(manager._processes) == 0
            
    finally:
        # 恢复原始环境变量
        if original_retention is not None:
            os.environ['PROCESS_RETENTION_SECONDS'] = original_retention
        else:
            os.environ.pop('PROCESS_RETENTION_SECONDS', None)