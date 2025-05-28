import os
import tempfile
from unittest.mock import AsyncMock

import pytest

from mcp_shell_server.shell_executor import default_shell_executor


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdirname:
        # Return the real path to handle macOS /private/tmp symlink
        yield os.path.realpath(tmpdirname)


@pytest.mark.asyncio
async def test_async_execute_basic():
    """Test basic functionality of async_execute method"""
    # Mock the process_manager.start_process method
    original_start_process = default_shell_executor.process_manager.start_process
    default_shell_executor.process_manager.start_process = AsyncMock(
        return_value="test-process-id"
    )

    try:
        # Test the async_execute method
        os.environ["ALLOW_COMMANDS"] = "echo"
        result = await default_shell_executor.async_execute(
            ["echo", "hello"], directory=os.getcwd(), description="Test async execute"
        )

        # Verify that start_process was called with the correct arguments
        default_shell_executor.process_manager.start_process.assert_called_once()
        args, kwargs = default_shell_executor.process_manager.start_process.call_args

        # Check the result
        assert result == "test-process-id"

    finally:
        # Restore the original method
        default_shell_executor.process_manager.start_process = original_start_process


@pytest.mark.asyncio
async def test_async_execute_validation():
    """Test validation in async_execute method"""
    # Empty command
    with pytest.raises(ValueError, match="Empty command"):
        await default_shell_executor.async_execute([], directory=os.getcwd())

    # Directory validation
    with pytest.raises(ValueError, match="Directory must be an absolute path"):
        await default_shell_executor.async_execute(
            ["echo", "hello"], directory="relative/path"
        )

    # Non-existent directory
    with pytest.raises(ValueError, match="Directory does not exist"):
        await default_shell_executor.async_execute(
            ["echo", "hello"], directory="/nonexistent/directory"
        )
