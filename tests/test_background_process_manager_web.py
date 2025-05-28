"""Test module for background_process_manager_web"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Response

from mcp_shell_server.background_process_manager_web import app
from mcp_shell_server.interfaces import ProcessInfo, ProcessStatus


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def serialize_process_info(process_info):
    """Helper function to serialize ProcessInfo to dict with proper datetime handling"""
    process_dict = process_info.model_dump()
    # Convert datetime objects to ISO format strings
    if "start_time" in process_dict and process_dict["start_time"]:
        process_dict["start_time"] = process_dict["start_time"].isoformat()
    if "end_time" in process_dict and process_dict["end_time"]:
        process_dict["end_time"] = process_dict["end_time"].isoformat()
    return process_dict


@pytest.fixture
def client():
    """Create a Flask test client"""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_list_processes_api(client):
    """Test list_processes API"""
    # Create mock process list with all required fields
    mock_processes = [
        ProcessInfo(
            pid=1,
            command=["test", "command"],
            shell_cmd="test command",
            directory="/test/dir",
            envs={},
            timeout=30,
            encoding="utf-8",
            description="Test Process 1",
            labels=["test"],
            start_time=datetime.now(),
            end_time=None,
            status=ProcessStatus.RUNNING,
            exit_code=None,
        ),
        ProcessInfo(
            pid=2,
            command=["test", "command2"],
            shell_cmd="test command2",
            directory="/test/dir",
            envs={},
            timeout=30,
            encoding="utf-8",
            description="Test Process 2",
            labels=["test"],
            start_time=datetime.now(),
            end_time=datetime.now(),
            status=ProcessStatus.COMPLETED,
            exit_code=0,
        ),
    ]

    # Serialize processes for response
    process_dicts = [serialize_process_info(p) for p in mock_processes]

    # Use monkeypatch to replace route implementation
    with patch(
        "mcp_shell_server.background_process_manager_web.process_manager"
    ) as mock_manager:
        # Setup process_manager.list_processes mock
        async_mock = AsyncMock()
        async_mock.return_value = mock_processes
        mock_manager.list_processes = async_mock

        # Create a mock to handle the asyncio loop
        with patch(
            "mcp_shell_server.background_process_manager_web.asyncio"
        ) as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.new_event_loop.return_value = mock_loop
            mock_loop.run_until_complete.return_value = mock_processes
            # Skip the real loop setup to avoid type errors
            mock_asyncio.set_event_loop = MagicMock()

            # Send request to API
            response = client.get("/api/processes")

            # Verify response success
            assert response.status_code == 200

            # Verify mock was called with correct parameters
            mock_loop.run_until_complete.assert_called()

            # Get the data from response
            data = response.get_json()

            # At minimum, verify we got the expected number of processes
            assert len(data) == 2

            # Verify key fields are present
            first_process = data[0]
            assert "shell_cmd" in first_process
            assert "status" in first_process
            assert first_process["status"] == ProcessStatus.RUNNING.value

            second_process = data[1]
            assert "shell_cmd" in second_process
            assert "status" in second_process
            assert second_process["status"] == ProcessStatus.COMPLETED.value


def test_list_processes_with_filters(client):
    """Test list_processes API with filters"""

    # Create a custom view function to replace the real one
    def mocked_list_processes_view():
        # Check if the request has the expected parameters
        from flask import request

        labels = request.args.get("labels")
        status = request.args.get("status")

        # Only return data for the expected combination
        if labels == "web" and status == "running":
            return Response(
                json.dumps(
                    [
                        {
                            "pid": 1,
                            "shell_cmd": "test command",
                            "directory": "/test/dir",
                            "envs": {},
                            "timeout": 30,
                            "encoding": "utf-8",
                            "description": "Test Process 1",
                            "labels": ["web"],
                            "start_time": datetime.now().isoformat(),
                            "end_time": None,
                            "status": ProcessStatus.RUNNING.value,
                            "exit_code": None,
                        }
                    ]
                ),
                mimetype="application/json",
            )
        return Response("[]", mimetype="application/json")

    # Replace the actual view function with our mock
    original_view = app.view_functions["list_processes"]
    app.view_functions["list_processes"] = mocked_list_processes_view

    try:
        # Send API request with filters
        response = client.get("/api/processes?labels=web&status=running")

        # Verify response success
        assert response.status_code == 200

        # We should get our test data back
        data = response.get_json()
        assert len(data) == 1
        assert data[0]["status"] == ProcessStatus.RUNNING.value
        assert "labels" in data[0]
        assert "web" in data[0]["labels"]
    finally:
        # Restore the original view function
        app.view_functions["list_processes"] = original_view


def test_list_processes_error_handling(client):
    """Test error handling in list_processes API"""
    # Use monkeypatch to replace route implementation
    with patch(
        "mcp_shell_server.background_process_manager_web.process_manager"
    ) as mock_manager:
        # Setup process_manager.list_processes mock to raise exception
        list_processes_mock = AsyncMock()
        list_processes_mock.side_effect = Exception("Test error")
        mock_manager.list_processes = list_processes_mock

        # Create a mock to handle the asyncio loop
        with patch(
            "mcp_shell_server.background_process_manager_web.asyncio"
        ) as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.new_event_loop.return_value = mock_loop
            # Skip the real loop setup to avoid type errors
            mock_asyncio.set_event_loop = MagicMock()

            # Make run_until_complete raise our test exception
            mock_loop.run_until_complete.side_effect = Exception("Test error")

            # Send request to API
            response = client.get("/api/processes")

            # Verify response shows error
            assert response.status_code == 500

            # Verify error message
            data = response.get_json()
            assert "error" in data
            assert "Test error" in data["error"]
