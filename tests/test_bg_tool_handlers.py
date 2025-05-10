"""Tests for the bg_tool_handlers module."""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from mcp_shell_server.bg_tool_handlers import (
    StartProcessArgs,
    ListProcessesArgs,
    StopProcessArgs,
    GetProcessOutputArgs,
    StartBackgroundProcessToolHandler,
    ListBackgroundProcessesToolHandler,
    StopBackgroundProcessToolHandler,
    GetBackgroundProcessOutputToolHandler,
    background_process_manager,
)


def test_start_process_args_validation():
    """测试StartProcessArgs参数验证"""
    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        # 有效的参数
        args = StartProcessArgs(
            command=["echo", "test"],
            directory=temp_dir,
            description="Test command"
        )
        assert args.command == ["echo", "test"]
        assert args.directory == temp_dir
        assert args.description == "Test command"
        assert args.labels is None
        assert args.stdin is None
        assert args.envs is None
        assert args.encoding is None
        assert args.timeout is None
        
        # 测试command不能为空
        with pytest.raises(ValidationError, match="Command cannot be empty"):
            StartProcessArgs(
                command=[],
                directory=temp_dir,
                description="Empty command"
            )
        
        # 测试directory必须存在
        with pytest.raises(ValidationError, match="Directory .* does not exist"):
            StartProcessArgs(
                command=["echo", "test"],
                directory="/non_existent_directory",
                description="Invalid directory"
            )


def test_list_processes_args_validation():
    """测试ListProcessesArgs参数验证"""
    # 有效的参数
    args = ListProcessesArgs()
    assert args.labels is None
    assert args.status is None
    
    args = ListProcessesArgs(labels=["test", "example"])
    assert args.labels == ["test", "example"]
    
    args = ListProcessesArgs(status="running")
    assert args.status == "running"
    
    # 无效的状态
    with pytest.raises(ValidationError, match="Status must be one of"):
        ListProcessesArgs(status="invalid_status")


def test_stop_process_args_validation():
    """测试StopProcessArgs参数验证"""
    args = StopProcessArgs(process_id="test123")
    assert args.process_id == "test123"
    assert args.force is False
    
    args = StopProcessArgs(process_id="test123", force=True)
    assert args.process_id == "test123"
    assert args.force is True


def test_get_process_output_args_validation():
    """测试GetProcessOutputArgs参数验证"""
    # 基本参数
    args = GetProcessOutputArgs(process_id="test123")
    assert args.process_id == "test123"
    assert args.tail is None
    assert args.since is None
    assert args.until is None
    assert args.with_stdout is True
    assert args.with_stderr is False
    assert args.add_time_prefix is True
    assert args.time_prefix_format == "%Y-%m-%d %H:%M:%S.%f"
    
    # 完整参数
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    
    args = GetProcessOutputArgs(
        process_id="test123",
        tail=10,
        since=one_hour_ago,
        until=now,
        with_stdout=False,
        with_stderr=True,
        add_time_prefix=False,
        time_prefix_format="%H:%M:%S"
    )
    assert args.process_id == "test123"
    assert args.tail == 10
    assert args.since == one_hour_ago
    assert args.until == now
    assert args.with_stdout is False
    assert args.with_stderr is True
    assert args.add_time_prefix is False
    assert args.time_prefix_format == "%H:%M:%S"
    
    # 字符串日期转换
    args = GetProcessOutputArgs(
        process_id="test123",
        since="2021-01-01T12:00:00",
        until="2021-01-02T12:00:00"
    )
    assert args.since == datetime(2021, 1, 1, 12, 0, 0)
    assert args.until == datetime(2021, 1, 2, 12, 0, 0)
    
    # 无效的日期格式
    with pytest.raises(ValidationError, match="must be a valid ISO format"):
        GetProcessOutputArgs(
            process_id="test123",
            since="invalid-date"
        )
    
    with pytest.raises(ValidationError, match="must be a valid ISO format"):
        GetProcessOutputArgs(
            process_id="test123",
            until="invalid-date"
        )
    
    # tail必须大于0
    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        GetProcessOutputArgs(
            process_id="test123",
            tail=0
        )


@pytest.mark.asyncio
async def test_get_process_output_tool_handler():
    """测试GetBackgroundProcessOutputToolHandler"""
    handler = GetBackgroundProcessOutputToolHandler()
    
    # 创建模拟进程
    mock_process = MagicMock()
    mock_process.process_id = "test123"
    mock_process.command = ["echo", "test"]
    mock_process.description = "Test process"
    mock_process.status = "running"
    
    # 模拟get_process_output方法
    output_data = [
        {"timestamp": datetime.now(), "text": "Test output", "stream": "stdout"}
    ]
    
    # 模拟background_process_manager
    with patch("mcp_shell_server.bg_tool_handlers.background_process_manager") as mock_manager:
        # 将方法变为异步模拟
        mock_manager.get_process = AsyncMock(return_value=mock_process)
        mock_manager.get_process_output = AsyncMock(return_value=output_data)
        
        # 测试标准输出
        args = GetProcessOutputArgs(
            process_id="test123",
            since=datetime.now() - timedelta(hours=1),
            with_stdout=True,
            with_stderr=False
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 2  # 现在返回两个TextContent
        assert "Process test123" in result[0].text  # 第一个是进程信息
        assert "stdout" in result[1].text  # 第二个是标准输出内容
        
        # 验证调用
        mock_manager.get_process_output.assert_called_once()
        call_args = mock_manager.get_process_output.call_args[1]
        assert call_args["process_id"] == "test123"
        assert call_args["since_time"] is not None  # 时间转换为ISO格式
        assert call_args["error"] is False
        
        # 测试错误输出
        mock_manager.get_process_output.reset_mock()
        
        args = GetProcessOutputArgs(
            process_id="test123",
            with_stdout=False,
            with_stderr=True
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 2  # 现在返回两个TextContent
        assert "Process test123" in result[0].text  # 第一个是进程信息
        assert "stderr" in result[1].text  # 第二个是错误输出内容
        
        # 验证调用
        mock_manager.get_process_output.assert_called_once()
        call_args = mock_manager.get_process_output.call_args[1]
        assert call_args["process_id"] == "test123"
        assert call_args["error"] is True
        
        # 测试同时获取标准输出和错误输出
        mock_manager.get_process_output.reset_mock()
        
        args = GetProcessOutputArgs(
            process_id="test123",
            with_stdout=True,
            with_stderr=True
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 3  # 返回三个TextContent(进程信息、stderr、stdout)
        assert "Process test123" in result[0].text  # 第一个是进程信息
        assert "stdout:" in result[1].text  # 第二个是标准输出
        assert "stderr:" in result[2].text  # 第三个是错误输出
        
        
        # 验证调用
        # 现在会调用 get_process_output 两次，一次用于 stderr，一次用于 stdout
        assert mock_manager.get_process_output.call_count == 2
        
        # 测试无时间前缀
        mock_manager.get_process_output.reset_mock()
        
        args = GetProcessOutputArgs(
            process_id="test123",
            with_stdout=True,
            with_stderr=False,
            add_time_prefix=False
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 2  # 进程信息和标准输出
        assert "stdout:" in result[1].text  # 输出标题格式正确
        assert "lines" in result[1].text  # 包含行数信息
        assert "Test output" in result[1].text  # 输出中包含文本
        assert "[" not in result[1].text.split("---\n")[2]  # 确认内容部分没有时间戳前缀 