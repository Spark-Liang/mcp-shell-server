"""Tests for the BackgroundProcessManager class."""

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_shell_server.backgroud_process_manager import (
    BackgroundProcess,
    BackgroundProcessManager,
    ProcessStatus,
)


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
            command=["echo", "test"],
            directory=temp_dir,
            description="Test background process",
            labels=["test"],
            stdin="input data",
        )
        
        # 验证进程创建
        assert bg_process.process_id is not None
        assert bg_process.command == ["echo", "test"]
        assert bg_process.directory == temp_dir
        assert bg_process.description == "Test background process"
        assert bg_process.labels == ["test"]
        assert bg_process.status == ProcessStatus.RUNNING
        assert bg_process.process == mock_proc
        
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
    mock_bg_process = MagicMock()
    mock_bg_process.process_id = "test-process-id"
    create_process_mock.return_value = mock_bg_process
    
    with patch.object(bg_process_manager, "create_process", create_process_mock):
        process_id = await bg_process_manager.start_process(
            command=["echo", "test"],
            directory=temp_dir,
            description="Test process",
            labels=["test", "example"],
        )
        
        # 验证返回的进程ID
        assert process_id == "test-process-id"
        
        # 验证create_process被正确调用
        create_process_mock.assert_awaited_once_with(
            command=["echo", "test"],
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
    process_id = "test-output-process"
    
    # 创建模拟后台进程
    bg_process = MagicMock()
    bg_process.process_id = process_id
    bg_process.status = ProcessStatus.RUNNING
    
    # 模拟输出获取方法
    output_data = [
        {"timestamp": datetime.now(), "text": "line 1"},
        {"timestamp": datetime.now(), "text": "line 2"},
    ]
    error_data = [
        {"timestamp": datetime.now(), "text": "error 1"},
    ]
    
    bg_process.get_output.return_value = output_data
    bg_process.get_error.return_value = error_data
    
    # 添加到进程字典
    bg_process_manager._processes[process_id] = bg_process
    
    # 测试获取标准输出
    stdout = await bg_process_manager.get_process_output(process_id)
    assert stdout == output_data
    bg_process.get_output.assert_called_once_with(tail=None, since=None, until=None)
    
    # 测试获取错误输出
    stderr = await bg_process_manager.get_process_output(process_id, error=True)
    assert stderr == error_data
    bg_process.get_error.assert_called_once_with(tail=None, since=None, until=None)
    
    # 测试带参数获取
    bg_process.get_output.reset_mock()
    
    since_time = (datetime.now() - timedelta(hours=1)).isoformat()
    await bg_process_manager.get_process_output(process_id, tail=10, since_time=since_time)
    
    # 验证参数传递正确
    call_args = bg_process.get_output.call_args[1]
    assert call_args["tail"] == 10
    assert isinstance(call_args["since"], datetime)  # 验证since_time被转换为datetime
    assert call_args["until"] is None  # 验证until为None
    
    # 测试获取不存在的进程输出
    with pytest.raises(ValueError, match="进程ID nonexistent 不存在"):
        await bg_process_manager.get_process_output("nonexistent")


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
        "process1": process1,
        "process2": process2
    }
    
    # 清理所有进程
    with patch.object(bg_process_manager, "stop_process", AsyncMock()) as mock_stop:
        await bg_process_manager.cleanup_all()
        
        # 验证运行中的进程被停止
        mock_stop.assert_called_once_with("process1", force=True)
        
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
    process1.process_id = "proc1"
    process1.labels = ["test", "web"]
    process1.status = ProcessStatus.RUNNING
    process1.is_running.return_value = True
    
    process2 = MagicMock()
    process2.process_id = "proc2"
    process2.labels = ["test", "db"]
    process2.status = ProcessStatus.COMPLETED
    process2.is_running.return_value = False
    
    process3 = MagicMock()
    process3.process_id = "proc3"
    process3.labels = ["db"]
    process3.status = ProcessStatus.FAILED
    process3.is_running.return_value = False
    
    # 准备清理方法的mock
    with patch.object(bg_process_manager, "cleanup_process", AsyncMock()) as mock_cleanup:
        # 测试按状态过滤 - 应该清理 COMPLETED 状态的进程
        # 重置进程字典
        bg_process_manager._processes = {
            "proc1": process1,
            "proc2": process2,
            "proc3": process3
        }
        count = await bg_process_manager.cleanup_processes(status=ProcessStatus.COMPLETED)
        assert count == 1
        mock_cleanup.assert_called_once_with("proc2")
        mock_cleanup.reset_mock()
        
        # 测试按标签过滤 - 应该清理标签为 "db" 的非运行状态进程
        # 重置进程字典
        bg_process_manager._processes = {
            "proc1": process1,
            "proc2": process2,
            "proc3": process3
        }
        count = await bg_process_manager.cleanup_processes(labels=["db"])
        assert count == 2  # proc2 和 proc3 都应该被清理
        assert mock_cleanup.call_count == 2
        mock_cleanup.reset_mock()
        
        # 测试不带过滤器 - 应该清理所有非运行状态的进程
        # 重置进程字典
        bg_process_manager._processes = {
            "proc1": process1,
            "proc2": process2,
            "proc3": process3
        }
        count = await bg_process_manager.cleanup_processes()
        assert count == 2  # proc2 和 proc3 都应该被清理
        assert mock_cleanup.call_count == 2


@pytest.mark.asyncio
async def test_get_all_output(bg_process_manager):
    """测试获取合并输出功能"""
    # 准备模拟进程对象
    process_id = "test-all-output"
    
    # 准备测试数据
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)
    
    # 记录确切的时间点
    timestamp1 = two_hours_ago
    timestamp2 = one_hour_ago
    timestamp3 = now
    timestamp4 = two_hours_ago.replace(minute=30)
    timestamp5 = now.replace(minute=15)
    
    stdout_data = [
        {"timestamp": timestamp1, "text": "stdout line 1"},
        {"timestamp": timestamp2, "text": "stdout line 2"},
        {"timestamp": timestamp3, "text": "stdout line 3"},
    ]
    
    stderr_data = [
        {"timestamp": timestamp4, "text": "stderr line 1"},
        {"timestamp": timestamp5, "text": "stderr line 2"},
    ]
    
    # 创建模拟进程
    mock_process = MagicMock()
    mock_process.get_output.return_value = stdout_data
    mock_process.get_error.return_value = stderr_data
    
    # 模拟get_process方法
    with patch.object(bg_process_manager, "get_process", AsyncMock(return_value=mock_process)):
        # 测试获取所有输出
        all_output = await bg_process_manager.get_all_output(process_id)
        
        # 验证输出合并和排序
        assert len(all_output) == 5  # 所有输出行
        
        # 验证按时间排序
        timestamps = [item["timestamp"] for item in all_output]
        assert timestamps == sorted(timestamps, key=lambda x: x)
        
        # 验证流类型标记
        stdout_count = sum(1 for item in all_output if item["stream"] == "stdout")
        stderr_count = sum(1 for item in all_output if item["stream"] == "stderr")
        assert stdout_count == 3
        assert stderr_count == 2
        
        # 测试带since_time参数
        since_time = timestamp2.isoformat()
        all_output = await bg_process_manager.get_all_output(process_id, since_time=since_time)
        
        # 验证过滤结果 - 应该只包含timestamp2及之后的记录
        assert len(all_output) == 3
        timestamps = [item["timestamp"] for item in all_output]
        assert all(ts >= timestamp2 for ts in timestamps)
        
        # 测试带until_time参数
        until_time = timestamp2.isoformat()
        all_output = await bg_process_manager.get_all_output(process_id, until_time=until_time)
        
        # 验证过滤结果 - 应该只包含timestamp2及之前的记录
        assert len(all_output) == 3
        timestamps = [item["timestamp"] for item in all_output]
        assert all(ts <= timestamp2 for ts in timestamps)
        
        # 测试同时使用since_time和until_time
        since_time = timestamp1.replace(minute=15).isoformat()
        until_time = timestamp3.replace(minute=30).isoformat()
        all_output = await bg_process_manager.get_all_output(process_id, since_time=since_time, until_time=until_time)
        
        # 验证在范围内的记录
        timestamps = [item["timestamp"] for item in all_output]
        since_dt = datetime.fromisoformat(since_time)
        until_dt = datetime.fromisoformat(until_time)
        assert all(since_dt <= ts <= until_dt for ts in timestamps)
        
        # 测试tail参数
        all_output = await bg_process_manager.get_all_output(process_id, tail=2)
        assert len(all_output) == 2  # 应该只有最后2行
        
        # 测试进程不存在
        with patch.object(bg_process_manager, "get_process", AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="进程 .* 不存在"):
                await bg_process_manager.get_all_output("nonexistent")


@pytest.mark.asyncio
async def test_follow_process_output(bg_process_manager):
    """测试实时跟踪进程输出"""
    process_id = "test-follow-output"
    
    # 创建模拟后台进程
    bg_process = MagicMock()
    bg_process.process_id = process_id
    
    # 模拟is_running方法，前两次调用返回True，第三次返回False
    is_running_mock = MagicMock()
    is_running_values = [True, True, False]
    is_running_mock.side_effect = is_running_values
    bg_process.is_running = is_running_mock
    
    # 模拟时间戳
    now = datetime.now()
    
    # 模拟初始输出
    initial_output = [
        {"timestamp": now, "text": "初始输出 1"},
    ]
    
    # 模拟后续输出
    new_output1 = [
        {"timestamp": now + timedelta(seconds=1), "text": "新输出 1"},
    ]
    
    new_output2 = [
        {"timestamp": now + timedelta(seconds=2), "text": "新输出 2"},
    ]
    
    final_output = [
        {"timestamp": now + timedelta(seconds=3), "text": "最终输出"},
    ]
    
    # 设置get_output返回值序列
    bg_process.get_output = AsyncMock()
    bg_process.get_output.side_effect = [
        initial_output,  # 初始调用
        new_output1,     # 第一次轮询
        new_output2,     # 第二次轮询
        final_output,    # 进程结束后的最终检查
    ]
    
    # 添加到进程字典
    bg_process_manager._processes[process_id] = bg_process
    
    # 使用较短的轮询间隔加速测试
    poll_interval = 0.01
    
    # 跟踪输出
    collected_outputs = []
    async for output in bg_process_manager.follow_process_output(
        process_id, poll_interval=poll_interval
    ):
        collected_outputs.append(output)
    
    # 验证收集的输出
    assert len(collected_outputs) == 4
    assert collected_outputs[0]["text"] == "初始输出 1"
    assert collected_outputs[1]["text"] == "新输出 1"
    assert collected_outputs[2]["text"] == "新输出 2"
    assert collected_outputs[3]["text"] == "最终输出"
    
    # 验证is_running被正确调用
    assert is_running_mock.call_count == 3
    
    # sleep会被调用，但我们不直接测试它 

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
            command=["sleep", "10"],  # 不会实际执行
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
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = MagicMock(return_value=(b"pipeline output", b""))
    mock_proc.wait = MagicMock(return_value=asyncio.Future())
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = MagicMock()
    mock_proc.stdin.close = MagicMock()
    
    # 准备测试命令
    commands = ["ls -la", "grep txt", "wc -l"]
    expected_pipeline = "ls -la | grep txt | wc -l"
    temp_dir = tempfile.gettempdir()
    
    with patch(
        "asyncio.create_subprocess_shell", 
        new_callable=AsyncMock, 
        return_value=mock_proc
    ) as mock_create, patch(
        "asyncio.iscoroutinefunction",
        return_value=False
    ), patch.object(
        bg_process_manager, "_monitor_process", AsyncMock()
    ):
        # 执行管道命令
        proc_id = await bg_process_manager.execute_pipeline(
            commands=commands,
            directory=temp_dir,
            description="测试管道命令",
            labels=["test", "pipeline"],
            first_stdin="test input",
        )
        
        # 验证进程创建
        assert proc_id is not None
        bg_process = bg_process_manager._processes[proc_id]
        
        # 验证命令被正确构建
        mock_create.assert_called_once()
        call_args = mock_create.call_args[0][0]
        assert expected_pipeline in call_args
        
        # 验证进程属性
        assert bg_process.description == "测试管道命令"
        assert set(bg_process.labels) == set(["test", "pipeline"])
        assert bg_process.directory == temp_dir
        
        # 验证stdin被传递
        mock_proc.stdin.write.assert_called_once()
        
    # 测试空命令列表
    with pytest.raises(ValueError, match="命令列表不能为空"):
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
        "proc1": proc1,
        "proc2": proc2,
        "proc3": proc3,
        "proc4": proc4,
        "proc5": proc5
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
                process_id="test1",
                command=["echo", "test1"],
                directory=temp_dir,
                description="Test process 1"
            )
            process1.status = ProcessStatus.COMPLETED
            process1.end_time = datetime.now() - timedelta(seconds=5)  # 5秒前结束
            
            process2 = BackgroundProcess(
                process_id="test2",
                command=["echo", "test2"],
                directory=temp_dir,
                description="Test process 2"
            )
            process2.status = ProcessStatus.COMPLETED
            process2.end_time = datetime.now()  # 刚刚结束
            
            # 模拟一个仍在运行的进程
            process3 = BackgroundProcess(
                process_id="test3",
                command=["echo", "test3"],
                directory=temp_dir,
                description="Test process 3"
            )
            
            # 添加进程到管理器
            manager._processes["test1"] = process1
            manager._processes["test2"] = process2
            manager._processes["test3"] = process3
            
            # 为已完成的进程安排延迟清理
            manager.schedule_delayed_cleanup("test1")
            manager.schedule_delayed_cleanup("test2")
            
            # 验证清理任务已安排
            assert process1.cleanup_scheduled
            assert process2.cleanup_scheduled
            assert process1.cleanup_handle is not None
            assert process2.cleanup_handle is not None
            assert not process3.cleanup_scheduled  # 运行中的进程不应该安排清理
            
            # 等待延迟清理执行（等待比保留时间稍长一点）
            await asyncio.sleep(1.5)
            
            # 检查进程1是否已被清理
            assert "test1" not in manager._processes
            
            # 确保进程3（运行中的进程）没有被清理
            assert "test3" in manager._processes
            
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