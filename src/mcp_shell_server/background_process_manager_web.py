"""Background process management web interface."""

import asyncio
import logging
import os
import sys

from flask import Flask, jsonify, render_template, request

from mcp_shell_server.interfaces import ProcessStatus

# 创建日志记录器
logger = logging.getLogger("mcp-shell-server")

# 全局变量保存URL前缀
url_prefix = ""

# 获取模板文件夹路径
def get_template_folder():
    """获取模板文件夹的绝对路径，兼容开发和打包环境"""
    # 首先尝试相对于当前文件的路径（开发环境）
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(current_dir, "templates")
    
    if os.path.exists(template_dir):
        return template_dir
    
    # 如果是打包后的环境，尝试在可执行文件目录中查找
    if hasattr(sys, '_MEIPASS'):  # PyInstaller
        template_dir = os.path.join(sys._MEIPASS, "mcp_shell_server", "templates")
    elif hasattr(sys, 'frozen'):  # 其他打包工具，包括 Nuitka
        # 获取可执行文件所在目录
        exe_dir = os.path.dirname(sys.executable)
        template_dir = os.path.join(exe_dir, "mcp_shell_server", "templates")
        
        # 如果在可执行文件目录找不到，尝试在内置数据路径
        if not os.path.exists(template_dir):
            # Nuitka 的数据文件路径
            import pkg_resources
            try:
                template_dir = pkg_resources.resource_filename('mcp_shell_server', 'templates')
            except:
                # 最后的备选方案：当前工作目录
                template_dir = os.path.join(os.getcwd(), "mcp_shell_server", "templates")
    
    return template_dir

# 创建Flask应用，使用动态模板路径
template_folder = get_template_folder()
logger.info(f"模板文件夹路径: {template_folder}")
logger.info(f"模板文件夹是否存在: {os.path.exists(template_folder)}")
if os.path.exists(template_folder):
    logger.info(f"模板文件夹内容: {os.listdir(template_folder)}")

app = Flask(__name__, template_folder=template_folder)

# 获取全局进程管理器
from .shell_executor import default_shell_executor

# 使用 ShellExecutor 的进程管理器实例
process_manager = default_shell_executor.process_manager


@app.route("/")
def index():
    """显示进程管理首页"""
    return render_template("process_list.html", url_prefix=url_prefix)


@app.route("/process/<int:pid>")
def process_detail(pid):
    """显示单个进程详细信息的页面"""
    # 根据进程ID获取进程信息，然后渲染模板
    return render_template("process_detail.html", pid=pid, url_prefix=url_prefix)


@app.route("/api/processes")
def list_processes():
    """获取所有进程信息"""
    # 从查询参数获取过滤条件
    labels = request.args.get("labels")
    status_str = request.args.get("status")

    # 转换标签为列表
    labels_list = labels.split(",") if labels else None

    # 转换状态字符串为枚举值
    status = ProcessStatus(status_str) if status_str else None

    # 创建事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 异步获取进程列表
        processes = loop.run_until_complete(
            process_manager.list_processes(labels=labels_list, status=status)
        )

        return jsonify([proc.model_dump() for proc in processes])
    except Exception as e:
        logger.exception(f"获取进程列表失败: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()


@app.route("/api/process/<int:pid>")
def get_process(pid):
    """获取单个进程信息"""
    # 创建事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 异步获取进程信息
        process = loop.run_until_complete(process_manager.get_process(pid))

        if not process:
            return jsonify({"error": f"Process {pid} not found"}), 404

        return jsonify(process.process_info.model_dump())
    except Exception as e:
        logger.exception(f"获取进程 {pid} 信息失败: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()


@app.route("/api/process/<int:pid>/output")
def get_process_output(pid):
    """获取进程输出"""
    # 从查询参数获取选项
    tail = request.args.get("tail", type=int)
    since = request.args.get("since")
    until = request.args.get("until")
    with_stdout = request.args.get("stdout", "true").lower() == "true"
    with_stderr = request.args.get("stderr", "false").lower() == "true"

    # 创建事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 验证进程存在
        process = loop.run_until_complete(process_manager.get_process(pid))
        if not process:
            return jsonify({"error": f"Process {pid} not found"}), 404

        # 获取标准输出
        stdout = []
        if with_stdout:
            stdout = loop.run_until_complete(
                process_manager.get_process_output(
                    pid=pid, tail=tail, since_time=since, until_time=until, error=False
                )
            )

        # 获取错误输出
        stderr = []
        if with_stderr:
            stderr = loop.run_until_complete(
                process_manager.get_process_output(
                    pid=pid, tail=tail, since_time=since, until_time=until, error=True
                )
            )

        # 转换为字典列表，使用model_dump()替代to_dict()
        result = {
            "stdout": [entry.model_dump() for entry in stdout],
            "stderr": [entry.model_dump() for entry in stderr],
        }

        return jsonify(result)
    except Exception as e:
        logger.exception(f"获取进程 {pid} 输出失败: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()


@app.route("/api/process/<int:pid>/stop", methods=["POST"])
def stop_process_api(pid):
    """停止进程"""
    try:
        # 从请求体获取选项
        force = request.json.get("force", False) if request.is_json else False

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 验证进程存在
            process = loop.run_until_complete(process_manager.get_process(pid))
            if not process:
                return jsonify({"error": f"Process {pid} not found"}), 404

            # 检查进程是否已经完成
            if process.status != ProcessStatus.RUNNING:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"Process is not running (status: {process.status.value})",
                        }
                    ),
                    400,
                )

            # 异步停止进程
            # 直接使用事件循环执行停止操作
            loop.run_until_complete(process_manager.stop_process(pid, force=force))

            return jsonify(
                {
                    "status": "success",
                    "message": f"Process {pid} stopped successfully",
                    "pid": pid,
                }
            )
        finally:
            loop.close()
    except Exception as e:
        logger.exception(f"停止进程 {pid} 失败: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/process/<int:pid>/clean", methods=["POST"])
def clean_process_api(pid):
    """清理进程"""
    try:
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 验证进程存在
            process = loop.run_until_complete(process_manager.get_process(pid))
            if not process:
                return jsonify({"error": f"Process {pid} not found"}), 404

            # 检查进程状态是否为运行中
            if process.status == ProcessStatus.RUNNING:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Process is still running and cannot be cleaned",
                        }
                    ),
                    400,
                )

            # 异步清理进程
            loop.run_until_complete(process_manager.clean_completed_process(pid))

            return jsonify(
                {
                    "status": "success",
                    "message": f"Process {pid} cleaned successfully",
                    "pid": pid,
                }
            )
        finally:
            loop.close()
    except Exception as e:
        logger.exception(f"清理进程 {pid} 失败: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/process/clean_all", methods=["POST"])
def clean_all_processes_api():
    """清理所有进程"""
    # 创建事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 异步清理所有进程
        count = loop.run_until_complete(process_manager.cleanup_all())

        return jsonify(
            {
                "status": "success",
                "message": f"Successfully cleaned {count} completed processes",
                "count": count,
            }
        )
    except Exception as e:
        logger.exception(f"清理所有进程失败: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        loop.close()


@app.route("/api/process/clean_selected", methods=["POST"])
def clean_selected_processes_api():
    """清理选定的进程"""
    # 检查请求体
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    # 获取进程ID列表
    pids = request.json.get("pids", [])
    if not pids:
        return jsonify({"error": "No process IDs provided"}), 400

    # 转换为整数类型
    pids = [int(pid) for pid in pids]

    # 结果记录
    results = {"success": [], "failed": [], "running": [], "not_found": []}

    # 创建事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 逐个清理进程
        for pid in pids:
            try:
                # 获取进程信息
                process = loop.run_until_complete(process_manager.get_process(pid))

                if not process:
                    results["not_found"].append(
                        {"pid": pid, "message": "Process not found"}
                    )
                    continue

                # 检查进程状态
                if process.status == ProcessStatus.RUNNING:
                    results["running"].append(
                        {"pid": pid, "message": "Process is still running"}
                    )
                    continue

                # 清理进程
                loop.run_until_complete(process_manager.clean_completed_process(pid))
                results["success"].append(
                    {"pid": pid, "message": "Process cleaned successfully"}
                )

            except Exception as e:
                logger.exception(f"清理进程 {pid} 失败: {str(e)}")
                results["failed"].append({"pid": pid, "message": str(e)})

        return jsonify(results)
    finally:
        loop.close()


# 启动函数
def start_web_interface(host="0.0.0.0", port=5000, debug=False, prefix=""):
    """启动Web界面

    Args:
        host: 监听的主机地址
        port: 监听的端口
        debug: 是否启用调试模式
        prefix: URL前缀，用于在子路径下运行应用
    """
    # 设置全局 URL 前缀，用于视图函数中传递给模板
    global url_prefix

    # 处理前缀格式
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix

    # 更新全局变量
    url_prefix = prefix

    if prefix:
        # 创建带有URL前缀的新应用
        application = Flask(__name__, template_folder=template_folder)

        # 设置静态文件路径
        application.static_url_path = f"{prefix}/static"
        application.static_folder = os.path.join(template_folder, "static")

        # 注册所有路由
        for rule in app.url_map.iter_rules():
            # 跳过静态文件路由
            if rule.endpoint == "static":
                continue
            # 添加带前缀的路由
            new_rule = url_prefix + rule.rule
            application.add_url_rule(
                prefix + rule.rule,
                endpoint=rule.endpoint,
                view_func=app.view_functions[rule.endpoint],
                methods=rule.methods,
                defaults=rule.defaults,
                strict_slashes=rule.strict_slashes,
            )

        # 启动前缀模式的应用
        application.run(host=host, port=port, debug=debug)
    else:
        # 启动原始应用
        app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    start_web_interface(debug=True)
