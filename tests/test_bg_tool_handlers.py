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
    assert args.error is False
    
    # 完整参数
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    
    args = GetProcessOutputArgs(
        process_id="test123",
        tail=10,
        since=one_hour_ago,
        until=now,
        error=True
    )
    assert args.process_id == "test123"
    assert args.tail == 10
    assert args.since == one_hour_ago
    assert args.until == now
    assert args.error is True
    
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
        mock_manager.get_all_output = AsyncMock(return_value=output_data)
        
        # 测试标准输出
        args = GetProcessOutputArgs(
            process_id="test123",
            since=datetime.now() - timedelta(hours=1)
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 1
        assert "Output from process" in result[0].text
        
        # 验证调用
        mock_manager.get_all_output.assert_called_once()
        call_args = mock_manager.get_all_output.call_args[1]
        assert call_args["process_id"] == "test123"
        assert call_args["since_time"] is not None  # 时间转换为ISO格式
        
        # 测试错误输出
        mock_manager.get_all_output.reset_mock()
        
        args = GetProcessOutputArgs(
            process_id="test123",
            error=True
        )
        
        result = await handler._do_run_tool(args)
        assert len(result) == 1
        assert "Error output from process" in result[0].text
        
        # 验证调用
        mock_manager.get_process_output.assert_called_once()
        call_args = mock_manager.get_process_output.call_args[1]
        assert call_args["process_id"] == "test123"
        assert call_args["error"] is True 