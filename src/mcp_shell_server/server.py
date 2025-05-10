import asyncio
import logging
import traceback
import sys
from typing import Any, Sequence, Union

import click
from mcp.server import Server
from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource

from .version import __version__
from .tool_handler import ToolHandler
from .exec_tool_handler import ExecuteToolHandler
from .bg_tool_handlers import bg_tool_handlers, background_process_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-shell-server")

app: Server = Server("mcp-shell-server")

# 初始化工具处理器列表
all_tool_handlers: list[ToolHandler] = [ExecuteToolHandler()] + bg_tool_handlers

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    # 返回所有工具定义
    return [handler.get_tool_def() for handler in all_tool_handlers]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[Union[TextContent, ImageContent, EmbeddedResource]]:
    """Handle tool calls"""
    try:
        # 查找匹配的工具处理器
        handler = next((h for h in all_tool_handlers if h.name == name), None)
        if not handler:
            raise ValueError(f"Unknown tool: {name}")

        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be a dictionary")

        return await handler.run_tool(arguments)

    except Exception as e:
        logger.error(traceback.format_exc())
        raise RuntimeError(f"Error executing command: {str(e)}") from e


async def run_stdio_server() -> None:
    """运行stdio服务器"""
    logger.info(f"Starting MCP shell server (stdio mode) v{__version__}")
    
    try:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream, app.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        # 确保在服务器关闭时清理所有后台进程
        await _cleanup_background_processes()


async def run_sse_server(host: str, port: int) -> None:
    """运行SSE服务器
    
    Args:
        host: 主机地址
        port: 端口号
    """
    logger.info(f"Starting MCP shell server (SSE mode) v{__version__} on {host}:{port}")
    
    try:
        from mcp.server.sse import sse_server

        async with sse_server(host=host, port=port) as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream, app.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        await _cleanup_background_processes()


async def run_http_server(host: str, port: int, path: str) -> None:
    """运行streamable HTTP服务器
    
    Args:
        host: 主机地址
        port: 端口号
        path: 路径
    """
    logger.info(f"Starting MCP shell server (HTTP mode) v{__version__} on {host}:{port}{path}")
    
    try:
        from mcp.server.streamable_http import streamable_http_server

        async with streamable_http_server(host=host, port=port, path=path) as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream, app.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        await _cleanup_background_processes()


async def _cleanup_background_processes() -> None:
    """清理后台进程"""
    try:
        logger.info("Cleaning up background processes...")
        await background_process_manager.cleanup_all()
        logger.info("Background process cleanup completed.")
    except Exception as cleanup_error:
        logger.error(f"Error during background process cleanup: {cleanup_error}")


# Click命令组
@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="mcp-shell-server")
@click.pass_context
def cli(ctx):
    """MCP Shell Server - 用于执行shell命令的MCP协议服务器"""
    # 如果没有提供子命令，默认使用stdio模式
    if ctx.invoked_subcommand is None:
        ctx.invoke(stdio)


@cli.command()
def stdio():
    """使用stdio模式启动服务器（默认模式）"""
    asyncio.run(run_stdio_server())


@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
def sse(host, port):
    """使用SSE模式启动服务器"""
    asyncio.run(run_sse_server(host, port))


@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
@click.option("--path", default="/mcp", help="服务器路径")
def http(host, port, path):
    """使用streamable HTTP模式启动服务器"""
    asyncio.run(run_http_server(host, port, path))


def main() -> None:
    """Main entry point for the MCP shell server"""
    # 判断是否通过测试调用
    # 如果是以模块方式运行的测试 (python -m pytest)，则通过引用方式调用直接执行 run_stdio_server
    if "pytest" in sys.modules:
        # 测试环境下不执行CLI，避免与测试用例冲突
        return
    
    # 执行Click命令组 - 正常执行模式
    cli(standalone_mode=True)
