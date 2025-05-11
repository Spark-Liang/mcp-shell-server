"""Background process management web interface."""

import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for

from mcp_shell_server.backgroud_process_manager import BackgroundProcessManager

# 创建日志记录器
logger = logging.getLogger("mcp-shell-server")

# 创建Flask应用
app = Flask(__name__, template_folder="templates")

# 全局后台进程管理器
from .bg_tool_handlers import background_process_manager

@app.route('/')
def index():
    """进程列表页面"""
    return render_template('process_list.html')

@app.route('/process/<process_id>')
def process_detail(process_id):
    """进程详情页面"""
    return render_template('process_detail.html', process_id=process_id)

@app.route('/api/processes')
def get_processes():
    """获取进程列表API"""
    # 异步转同步调用
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        labels = request.args.getlist('labels')
        status = request.args.get('status')
        
        processes = loop.run_until_complete(
            background_process_manager.list_processes(
                labels=labels if labels else None,
                status=status if status else None
            )
        )
        return jsonify(processes)
    finally:
        loop.close()

@app.route('/api/process/<process_id>')
def get_process(process_id):
    """获取单个进程信息API"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        process = loop.run_until_complete(background_process_manager.get_process(process_id))
        if not process:
            return jsonify({"error": "进程不存在"}), 404
        
        process_info = process.get_info()
        return jsonify(process_info)
    finally:
        loop.close()

@app.route('/api/process/<process_id>/output')
def get_process_output(process_id):
    """获取进程输出API"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 获取参数
        tail = request.args.get('tail', type=int)
        since = request.args.get('since')
        until = request.args.get('until')
        with_stderr = request.args.get('stderr', 'false').lower() == 'true'
        
        # 检查进程是否存在
        process = loop.run_until_complete(background_process_manager.get_process(process_id))
        if not process:
            return jsonify({"error": "进程不存在"}), 404
            
        # 获取进程输出
        stdout = loop.run_until_complete(
            background_process_manager.get_process_output(
                process_id=process_id,
                tail=tail,
                since_time=since,
                until_time=until,
                error=False
            )
        )
        
        # 如果需要，获取错误输出
        stderr = []
        if with_stderr:
            stderr = loop.run_until_complete(
                background_process_manager.get_process_output(
                    process_id=process_id,
                    tail=tail,
                    since_time=since,
                    until_time=until,
                    error=True
                )
            )
            
        return jsonify({
            "stdout": stdout,
            "stderr": stderr if with_stderr else []
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"获取进程输出时出错: {e}")
        return jsonify({"error": "获取进程输出时出错"}), 500
    finally:
        loop.close()

@app.route('/api/process/<process_id>/stop', methods=['POST'])
def stop_process_api(process_id):
    """停止进程API"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 获取是否强制停止的参数
        force = request.json.get('force', False) if request.is_json else False
        
        # 获取进程信息（用于返回消息）
        process = loop.run_until_complete(background_process_manager.get_process(process_id))
        if not process:
            return jsonify({"error": "进程不存在"}), 404
            
        # 检查进程是否正在运行
        if not process.is_running():
            return jsonify({"message": "进程已经停止，无需再次停止"}), 200
        
        # 停止进程
        result = loop.run_until_complete(
            background_process_manager.stop_process(process_id, force=force)
        )
        
        return jsonify({
            "success": result,
            "message": f"进程已{'强制' if force else ''}停止",
            "process_id": process_id
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"停止进程时出错: {e}")
        return jsonify({"error": f"停止进程时出错: {str(e)}"}), 500
    finally:
        loop.close()

@app.route('/api/process/<process_id>/clean', methods=['POST'])
def clean_process_api(process_id):
    """清理进程API"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 获取进程信息（用于返回消息）
        process = loop.run_until_complete(background_process_manager.get_process(process_id))
        if not process:
            return jsonify({"error": "进程不存在"}), 404
            
        # 清理进程
        result = loop.run_until_complete(
            background_process_manager.clean_completed_process(process_id)
        )
        
        return jsonify({
            "success": result,
            "message": "进程已清理",
            "process_id": process_id
        })
    except ValueError as e:
        # 如果进程仍在运行会抛出ValueErrpr
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"清理进程时出错: {e}")
        return jsonify({"error": f"清理进程时出错: {str(e)}"}), 500
    finally:
        loop.close()

@app.route('/api/processes/batch-clean', methods=['POST'])
def batch_clean_processes():
    """批量清理进程API"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 获取进程ID列表
        if not request.is_json:
            return jsonify({"error": "请求必须是JSON格式"}), 400
            
        process_ids = request.json.get('process_ids', [])
        if not process_ids:
            return jsonify({"error": "未提供进程ID列表"}), 400
            
        # 批量清理进程
        results = []
        for proc_id in process_ids:
            try:
                process = loop.run_until_complete(background_process_manager.get_process(proc_id))
                if not process:
                    results.append({
                        "process_id": proc_id,
                        "success": False,
                        "message": "进程不存在"
                    })
                    continue
                    
                # 尝试清理进程
                result = loop.run_until_complete(
                    background_process_manager.clean_completed_process(proc_id)
                )
                
                results.append({
                    "process_id": proc_id,
                    "success": result,
                    "message": "进程已清理"
                })
            except ValueError as e:
                results.append({
                    "process_id": proc_id,
                    "success": False,
                    "message": str(e)
                })
            except Exception as e:
                results.append({
                    "process_id": proc_id,
                    "success": False,
                    "message": f"清理时出错: {str(e)}"
                })
        
        return jsonify({
            "results": results,
            "success_count": sum(1 for r in results if r["success"]),
            "failure_count": sum(1 for r in results if not r["success"])
        })
    except Exception as e:
        logger.error(f"批量清理进程时出错: {e}")
        return jsonify({"error": f"批量清理进程时出错: {str(e)}"}), 500
    finally:
        loop.close()

# 启动函数
def start_web_interface(host='0.0.0.0', port=5000, debug=False, url_prefix=''):
    """启动Web界面
    
    Args:
        host: 监听的主机地址
        port: 监听的端口
        debug: 是否启用调试模式
        url_prefix: URL前缀，用于在子路径下运行应用
    """
    if url_prefix:
        if not url_prefix.startswith('/'):
            url_prefix = '/' + url_prefix
        # 创建一个具有URL前缀的应用
        application = Flask(__name__, template_folder="templates", static_url_path=f"{url_prefix}/static")
        # 注册路由时添加前缀
        for rule in app.url_map.iter_rules():
            # 跳过静态文件路由
            if rule.endpoint == 'static':
                continue
            # 添加带前缀的路由
            new_rule = url_prefix + rule.rule
            application.add_url_rule(
                new_rule,
                endpoint=rule.endpoint,
                view_func=app.view_functions[rule.endpoint],
                methods=rule.methods,
                defaults=rule.defaults,
                strict_slashes=rule.strict_slashes
            )
        # 启动应用
        application.run(host=host, port=port, debug=debug)
    else:
        # 直接启动原始应用
        app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    start_web_interface(debug=True)
