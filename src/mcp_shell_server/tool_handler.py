"""Tool handler abstraction for MCP shell server."""

import json
from typing import Any, Dict, List, Optional, Sequence, Type, Union, Generic, TypeVar
from abc import ABC, abstractmethod
from itertools import chain

from pydantic import BaseModel, ValidationError
from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource
import pydantic_core

T_ARGUMENTS = TypeVar('T_ARGUMENTS', bound=BaseModel)

class ToolHandler(Generic[T_ARGUMENTS], ABC):
    """抽象基类，定义工具处理器接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    @abstractmethod
    def argument_model(self) -> Type[T_ARGUMENTS]:
        """参数模型类型"""
        pass
    
    def get_tool_def(self) -> Tool:
        """
        获取工具定义
        
        基于name、description和argument_model属性生成Tool对象
        
        Returns:
            Tool对象
        """
        # 从模型中提取JSON Schema
        schema = self.argument_model.model_json_schema()
        
        # 确保schema是一个有效的JSON Schema对象
        if not isinstance(schema, dict):
            raise ValueError("Model schema must be a dictionary")
        
        # 转换为Tool的inputSchema格式
        input_schema = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=input_schema,
        )

    def _convert_to_content(
        self, result: Any
    ) -> Sequence[Union[TextContent, ImageContent, EmbeddedResource]]:
        """
        将任意类型的结果转换为内容对象序列
        
        Args:
            result: 任意类型的结果
            
        Returns:
            内容对象序列
        """
        if result is None:
            return []

        if isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
            return [result]

        if isinstance(result, (list, tuple)):
            return list(chain.from_iterable(self._convert_to_content(item) for item in result))

        if not isinstance(result, str):
            try:
                result = json.dumps(pydantic_core.to_jsonable_python(result))
            except Exception:
                result = str(result)

        return [TextContent(type="text", text=result)]

    async def run_tool(
        self, arguments: dict
    ) -> Sequence[Union[TextContent, ImageContent, EmbeddedResource]]:
        """
        处理工具调用
        
        Args:
            arguments: 工具参数字典
            
        Returns:
            内容对象序列
        """
        try:
            # 验证并转换参数
            validated_args = self.argument_model.model_validate(arguments)
            # 调用具体实现
            result = await self._do_run_tool(validated_args)
            # 确保返回的是适当的内容对象序列
            return self._convert_to_content(result)
        except ValidationError as e:
            # 转换为ValueError以保持与原始代码一致的异常类型
            raise ValueError(str(e))
    
    @abstractmethod
    async def _do_run_tool(self, arguments: T_ARGUMENTS) -> Any:
        """
        实际执行工具的抽象方法
        
        Args:
            arguments: 已验证的参数对象
            
        Returns:
            工具执行结果，可以是任何类型
        """
        pass
