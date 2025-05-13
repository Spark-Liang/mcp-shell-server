"""进程输出日志管理模块，用于管理后台进程的stdout和stderr日志。"""

import json
import os
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """日志条目模型，表示单条日志记录。"""
    timestamp: datetime = Field(..., description="日志记录时间戳")
    text: str = Field("", description="日志内容")


class OutputLogger(ABC):
    """输出日志记录器接口，定义日志读写操作。"""

    @abstractmethod
    def add_line(self, line: str) -> None:
        """添加单行日志。
        
        Args:
            line: 日志内容
        """
        pass
    
    @abstractmethod
    def add_lines(self, lines: List[str]) -> None:
        """批量添加多行日志。
        
        Args:
            lines: 日志内容列表
        """
        pass
    
    @abstractmethod
    def get_logs(
        self, 
        tail: Optional[int] = None, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None
    ) -> List[LogEntry]:
        """获取符合条件的日志。
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的日志
            until: 只返回指定时间之前的日志
            
        Returns:
            日志记录列表，每条记录为LogEntry对象，包含timestamp和text字段
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭日志并清理资源。"""
        pass


class JsonOutputLogger(OutputLogger):
    """使用JSON格式记录日志的实现。"""
    
    def __init__(self, log_path: str):
        """初始化JSON日志记录器。
        
        Args:
            log_path: 日志文件路径
        """
        self.log_path = log_path
        self.log_dir = os.path.dirname(log_path)
        
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 创建空日志文件
        with open(self.log_path, 'w', encoding='utf-8') as f:
            pass
    
    def add_line(self, line: str) -> None:
        """添加单行日志。
        
        Args:
            line: 日志内容
        """
        timestamp = datetime.now()
        log_entry = {
            "timestamp": timestamp.isoformat(),
            "text": line
        }
        
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"写入日志时出错: {e}")
    
    def add_lines(self, lines: List[str]) -> None:
        """批量添加多行日志。
        
        Args:
            lines: 日志内容列表
        """
        if not lines:
            return
            
        timestamp = datetime.now()
        
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                for line in lines:
                    log_entry = {
                        "timestamp": timestamp.isoformat(),
                        "text": line
                    }
                    f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"批量写入日志时出错: {e}")
    
    def get_logs(
        self, 
        tail: Optional[int] = None, 
        since: Optional[datetime] = None, 
        until: Optional[datetime] = None
    ) -> List[LogEntry]:
        """获取符合条件的日志。
        
        Args:
            tail: 只返回最后的n行
            since: 只返回指定时间之后的日志
            until: 只返回指定时间之前的日志
            
        Returns:
            日志记录列表，每条记录为LogEntry对象，包含timestamp和text字段
        """
        result = []
        
        if not os.path.exists(self.log_path):
            return []
        
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for line in lines:
                if not line.strip():
                    continue
                    
                try:
                    log_data = json.loads(line)
                    timestamp_str = log_data.get("timestamp")
                    
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str)
                        
                        # 应用过滤条件
                        if since and timestamp < since:
                            continue
                        if until and timestamp > until:
                            continue
                            
                        result.append(LogEntry(
                            timestamp=timestamp,
                            text=log_data.get("text", "")
                        ))
                except json.JSONDecodeError:
                    logger.warning(f"解析日志行失败: {line}")
                except Exception as e:
                    logger.warning(f"处理日志时出错: {e}")
            
            # 应用tail限制
            if tail is not None and tail > 0 and result:
                result = result[-tail:]
                
        except Exception as e:
            logger.error(f"读取日志文件时出错: {e}")
            
        return result
    
    def close(self) -> None:
        """关闭日志并清理资源。"""
        try:
            if os.path.exists(self.log_path):
                os.unlink(self.log_path)
                
            # 如果目录为空，则删除目录
            log_dir = Path(self.log_dir)
            if log_dir.exists() and not any(log_dir.iterdir()):
                shutil.rmtree(log_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"清理日志资源时出错: {e}")


class OutputManager:
    """输出日志管理器，负责创建和管理OutputLogger实例。"""
    
    def __init__(self):
        """初始化输出日志管理器。"""
        self._loggers: Dict[str, OutputLogger] = {}
    
    def get_logger(self, log_path: str) -> OutputLogger:
        """获取指定路径的日志记录器，如不存在则创建。
        
        Args:
            log_path: 日志文件路径
            
        Returns:
            OutputLogger: 日志记录器实例
        """
        if log_path not in self._loggers:
            self._loggers[log_path] = JsonOutputLogger(log_path)
            
        return self._loggers[log_path]
    
    def close_logger(self, log_path: str) -> None:
        """关闭并清理指定的日志记录器。
        
        Args:
            log_path: 日志文件路径
        """
        if log_path in self._loggers:
            self._loggers[log_path].close()
            del self._loggers[log_path]
    
    def close_all(self) -> None:
        """关闭所有日志记录器。"""
        for log_path in list(self._loggers.keys()):
            self.close_logger(log_path) 