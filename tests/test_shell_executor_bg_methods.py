import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from typing import List

from mcp_shell_server.shell_executor import default_shell_executor
from mcp_shell_server.interfaces import ProcessInfo, ProcessStatus, LogEntry


@pytest.mark.asyncio
async def test_list_processes():
    """Test list_processes method delegates correctly to process_manager"""
    # Mock data
    mock_processes = [
        ProcessInfo(
            pid=1,
            shell_cmd="echo hello",
            directory="/tmp",
            envs={},
            timeout=None,
            encoding="utf-8",
            description="Test process",
            labels=["test"],
            start_time=datetime.now(),
            end_time=None,
            status=ProcessStatus.RUNNING,
            exit_code=None
        )
    ]
    
    # Mock the process_manager.list_processes method
    original_list_processes = default_shell_executor.process_manager.list_processes
    default_shell_executor.process_manager.list_processes = AsyncMock(return_value=mock_processes)
    
    try:
        # Test without filters
        result = await default_shell_executor.list_processes()
        default_shell_executor.process_manager.list_processes.assert_called_with(
            labels=None, status=None
        )
        assert result == mock_processes
        
        # Test with filters
        labels = ["test"]
        status = ProcessStatus.RUNNING
        await default_shell_executor.list_processes(labels=labels, status=status)
        default_shell_executor.process_manager.list_processes.assert_called_with(
            labels=labels, status=status
        )
    finally:
        # Restore the original method
        default_shell_executor.process_manager.list_processes = original_list_processes


@pytest.mark.asyncio
async def test_get_process():
    """Test get_process method delegates correctly to process_manager"""
    # Mock data
    mock_process = MagicMock()
    
    # Mock the process_manager.get_process method
    original_get_process = default_shell_executor.process_manager.get_process
    default_shell_executor.process_manager.get_process = AsyncMock(return_value=mock_process)
    
    try:
        # Test get_process
        result = await default_shell_executor.get_process("test-pid")
        default_shell_executor.process_manager.get_process.assert_called_with("test-pid")
        assert result == mock_process
    finally:
        # Restore the original method
        default_shell_executor.process_manager.get_process = original_get_process


@pytest.mark.asyncio
async def test_stop_process():
    """Test stop_process method delegates correctly to process_manager"""
    # Mock the process_manager.stop_process method
    original_stop_process = default_shell_executor.process_manager.stop_process
    default_shell_executor.process_manager.stop_process = AsyncMock(return_value=True)
    
    try:
        # Test without force
        result = await default_shell_executor.stop_process("test-pid")
        default_shell_executor.process_manager.stop_process.assert_called_with(
            "test-pid", force=False
        )
        assert result is True
        
        # Test with force
        result = await default_shell_executor.stop_process("test-pid", force=True)
        default_shell_executor.process_manager.stop_process.assert_called_with(
            "test-pid", force=True
        )
        assert result is True
    finally:
        # Restore the original method
        default_shell_executor.process_manager.stop_process = original_stop_process


@pytest.mark.asyncio
async def test_get_process_output():
    """Test get_process_output method delegates correctly to process_manager"""
    # Mock data
    mock_entries = [
        LogEntry(timestamp=datetime.now(), text="test output", stream="stdout")
    ]
    
    # Mock the process_manager.get_process_output method
    original_get_process_output = default_shell_executor.process_manager.get_process_output
    default_shell_executor.process_manager.get_process_output = AsyncMock(return_value=mock_entries)
    
    try:
        # Test without optional parameters
        result = await default_shell_executor.get_process_output("test-pid")
        default_shell_executor.process_manager.get_process_output.assert_called_with(
            pid="test-pid",
            tail=None,
            since_time=None,
            until_time=None,
            error=False
        )
        assert result == mock_entries
        
        # Test with all parameters
        since = datetime(2023, 1, 1)
        until = datetime(2023, 12, 31)
        result = await default_shell_executor.get_process_output(
            "test-pid", tail=10, since=since, until=until, error=True
        )
        default_shell_executor.process_manager.get_process_output.assert_called_with(
            pid="test-pid",
            tail=10,
            since_time=since.isoformat(),
            until_time=until.isoformat(),
            error=True
        )
        assert result == mock_entries
    finally:
        # Restore the original method
        default_shell_executor.process_manager.get_process_output = original_get_process_output 