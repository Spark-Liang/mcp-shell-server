import asyncio
import logging
import traceback
import sys
import threading
import socket
from typing import Any, Sequence, Union, Optional, List

import click
from mcp.server import Server
from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource

from .version import __version__
from .interfaces import ToolHandler
from .exec_tool_handler import ExecuteToolHandler
from .bg_tool_handlers import bg_tool_handlers, background_process_manager
from . import backgroud_process_manager_web as web_server

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-shell-server")

app: Server = Server("mcp-shell-server")

# 初始化工具处理器列表
all_tool_handlers: list[ToolHandler] = [ExecuteToolHandler()] + bg_tool_handlers

# 用于存储web服务器线程
web_server_thread = None

def get_free_port() -> int:
    """获取一个可用的随机端口
    
    Returns:
        int: 可用的端口号
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('0.0.0.0', 0))
        return s.getsockname()[1]

def get_local_ip_addresses() -> List[str]:
    """获取本机所有IP地址
    
    Returns:
        List[str]: IP地址列表
    """
    try:
        # 获取主机名
        hostname = socket.gethostname()
        # 获取所有IP地址
        ip_list = []
        # 尝试获取IPv4地址
        try:
            ip_list.append(socket.gethostbyname(hostname))
        except Exception:
            pass
            
        # 尝试获取所有网络接口
        try:
            addresses = socket.getaddrinfo(
                host=hostname, 
                port=None, 
                family=socket.AF_INET  # 只获取IPv4地址
            )
            for addr in addresses:
                ip = addr[4][0]
                if ip not in ip_list and not ip.startswith('127.'):
                    ip_list.append(ip)
        except Exception:
            pass
            
        return ip_list
    except Exception:
        # 如果出现任何错误，返回空列表
        return []

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


async def run_stdio_server(web_host: str = '0.0.0.0', web_port: Optional[int] = None, web_path: Optional[str] = None) -> None:
    """运行stdio服务器
    
    Args:
        web_host: Web服务器的主机地址
        web_port: Web服务器的端口号，如果为None则使用随机端口
        web_path: Web服务器的URL前缀
    """
    logger.info(f"Starting MCP shell server (stdio mode) v{__version__}")
    
    # 启动Web服务器
    start_web_server(host=web_host, port=web_port, url_prefix=web_path)
    
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


async def run_sse_server(host: str, port: int, web_path: Optional[str] = None) -> None:
    """运行SSE服务器
    
    Args:
        host: 主机地址
        port: 端口号
        web_path: Web服务器的路径，如果为None则使用与SSE服务器相同的主机和端口
    """
    logger.info(f"Starting MCP shell server (SSE mode) v{__version__} on {host}:{port}")
    
    # 启动Web服务器，使用相同的主机和端口（如果未指定web_path）
    if web_path is None:
        web_host, web_port = host, port
        web_url_prefix = ''
    else:
        # 如果指定了不同的web_path，则使用默认主机和随机端口
        web_host, web_port = '0.0.0.0', None
        web_url_prefix = web_path.lstrip('/')
    
    start_web_server(host=web_host, port=web_port, url_prefix=web_url_prefix)
    
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


async def run_http_server(host: str, port: int, path: str, web_path: Optional[str] = None) -> None:
    """运行streamable HTTP服务器
    
    Args:
        host: 主机地址
        port: 端口号
        path: 路径
        web_path: Web服务器路径，不指定则与HTTP服务器共用同一端口
    """
    logger.info(f"Starting MCP shell server (HTTP mode) v{__version__} on {host}:{port}{path}")
    
    # 启动Web服务器，使用相同的主机和端口（如果未指定web_path）
    if web_path is None:
        web_host, web_port = host, port
        web_url_prefix = ''
    else:
        # 如果指定了不同的web_path，则使用默认主机和随机端口
        web_host, web_port = '0.0.0.0', None
        web_url_prefix = web_path.lstrip('/')
    
    start_web_server(host=web_host, port=web_port, url_prefix=web_url_prefix)
    
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


def start_web_server(host: str = '0.0.0.0', port: Optional[int] = None, debug: bool = False, url_prefix: str = '') -> None:
    """在独立线程中启动Web服务器
    
    Args:
        host: 主机地址，默认为0.0.0.0
        port: 端口号，如果为None则使用随机端口
        debug: 是否开启调试模式
        url_prefix: URL前缀，用于在子路径下运行应用
    """
    global web_server_thread
    
    # 如果端口未指定，获取随机端口
    if port is None:
        port = get_free_port()
    
    def run_web_server():
        """在线程中运行Web服务器"""
        try:
            web_server.start_web_interface(host=host, port=port, debug=debug, url_prefix=url_prefix)
        except Exception as e:
            logger.error(f"Error starting Web interface: {e}")
    
    # 创建并启动新线程
    web_server_thread = threading.Thread(target=run_web_server, daemon=True)
    web_server_thread.start()
    
    # 构建URL前缀字符串
    prefix_str = f"/{url_prefix}" if url_prefix else ""
    
    # 记录Web界面地址
    logger.info(f"Web 管理界面启动在端口 {port}")
    
    # 如果绑定的是所有接口(0.0.0.0)，则显示localhost和实际的IP地址
    if host == '0.0.0.0':
        logger.info(f"您可以访问: http://localhost:{port}{prefix_str}")
        
        # 获取本机所有IP地址
        ip_addresses = get_local_ip_addresses()
        if ip_addresses:
            for ip in ip_addresses:
                logger.info(f"局域网访问地址: http://{ip}:{port}{prefix_str}")
    else:
        # 使用指定的主机地址
        logger.info(f"您可以访问: http://{host}:{port}{prefix_str}")


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
@click.option("--web-host", default="0.0.0.0", help="Web服务器主机地址")
@click.option("--web-port", default=None, type=int, help="Web服务器端口，不指定则使用随机端口")
@click.option("--web-path", default="/web", help="Web服务器路径")
def stdio(web_host, web_port, web_path):    
    """使用stdio模式启动服务器（默认模式）"""
    asyncio.run(run_stdio_server(web_host=web_host, web_port=web_port, web_path=web_path))


@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
@click.option("--web-path", default="/web", help="Web服务器路径，不指定则与SSE服务器共用同一端口")
def sse(host, port, web_path):
    """使用SSE模式启动服务器"""
    asyncio.run(run_sse_server(host, port, web_path))


@cli.command()
@click.option("--host", default="127.0.0.1", help="服务器主机地址")
@click.option("--port", default=8000, type=int, help="服务器端口")
@click.option("--path", default="/mcp", help="服务器路径")
@click.option("--web-path", default="/web", help="Web服务器路径，不指定则与HTTP服务器共用同一端口")
def http(host, port, path, web_path):
    """使用streamable HTTP模式启动服务器"""
    asyncio.run(run_http_server(host, port, path, web_path))


def main() -> None:
    """Main entry point for the MCP shell server"""
    # 判断是否通过测试调用
    # 如果是以模块方式运行的测试 (python -m pytest)，则通过引用方式调用直接执行 run_stdio_server
    if "pytest" in sys.modules:
        # 测试环境下不执行CLI，避免与测试用例冲突
        return
    
    # 执行Click命令组 - 正常执行模式
    cli(standalone_mode=True)
