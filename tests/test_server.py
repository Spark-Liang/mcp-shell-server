# from mcp_shell_server.server import call_tool, list_tools


# @pytest.mark.asyncio
# async def test_list_tools():
#     """Test listing of available tools"""
#     tools = await list_tools()
#     assert len(tools) >= 1
#     tool = tools[0]
#     assert isinstance(tool, Tool)
#     assert tool.name == "shell_execute"
#     assert tool.description
#     assert tool.inputSchema["type"] == "object"


# @pytest.mark.asyncio
# async def test_call_tool_unknown_tool():
#     """Test calling an unknown tool"""
#     with pytest.raises(RuntimeError) as excinfo:
#         await call_tool("unknown_tool", {})
#     assert "Unknown tool: unknown_tool" in str(excinfo.value)


# @pytest.mark.asyncio
# async def test_call_tool_invalid_arguments():
#     """Test calling a tool with invalid arguments"""
#     with pytest.raises(RuntimeError) as excinfo:
#         await call_tool("shell_execute", "not a dict")
#     assert "Arguments must be a dictionary" in str(excinfo.value)


# async def test_main_server(mocker):
#     """Test the main server function"""
#     # Mock the stdio_server
#     mock_read_stream = mocker.AsyncMock()
#     mock_write_stream = mocker.AsyncMock()

#     # Create an async context manager mock
#     context_manager = mocker.AsyncMock()
#     context_manager.__aenter__ = mocker.AsyncMock(
#         return_value=(mock_read_stream, mock_write_stream)
#     )
#     context_manager.__aexit__ = mocker.AsyncMock(return_value=None)

#     # Set up stdio_server mock to return a regular function that returns the context manager
#     def stdio_server_impl():
#         return context_manager

#     mock_stdio_server = mocker.Mock(side_effect=stdio_server_impl)

#     # Mock app.run and create_initialization_options
#     mock_server_run = mocker.patch("mcp_shell_server.server.app.run")
#     mock_create_init_options = mocker.patch(
#         "mcp_shell_server.server.app.create_initialization_options"
#     )

#     # Import run_stdio_server after setting up mocks
#     from mcp_shell_server.server import run_stdio_server

#     # Execute run_stdio_server function
#     mocker.patch("mcp.server.stdio.stdio_server", mock_stdio_server)
#     await run_stdio_server()

#     # Verify interactions
#     mock_stdio_server.assert_called_once()
#     context_manager.__aenter__.assert_awaited_once()
#     context_manager.__aexit__.assert_awaited_once()
#     mock_server_run.assert_called_once_with(
#         mock_read_stream, mock_write_stream, mock_create_init_options.return_value
#     )


# @pytest.mark.asyncio
# async def test_main_server_error_handling(mocker):
#     """Test error handling in the main server function"""
#     # Mock app.run to raise an exception
#     mocker.patch(
#         "mcp_shell_server.server.app.run", side_effect=RuntimeError("Test error")
#     )

#     # Mock the stdio_server
#     context_manager = mocker.AsyncMock()
#     context_manager.__aenter__ = mocker.AsyncMock(
#         return_value=(mocker.AsyncMock(), mocker.AsyncMock())
#     )
#     context_manager.__aexit__ = mocker.AsyncMock(return_value=None)

#     def stdio_server_impl():
#         return context_manager

#     mock_stdio_server = mocker.Mock(side_effect=stdio_server_impl)

#     # Import run_stdio_server after setting up mocks
#     from mcp_shell_server.server import run_stdio_server

#     # Execute function and expect it to raise the error
#     mocker.patch("mcp.server.stdio.stdio_server", mock_stdio_server)
#     with pytest.raises(RuntimeError) as exc:
#         await run_stdio_server()

#     assert str(exc.value) == "Test error"
