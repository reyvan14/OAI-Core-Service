"""
Agent基类 - 提供标准化的Agent开发接口

所有自定义Agent应继承此基类并实现process方法
"""

import logging
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Agent基类，定义标准接口"""

    def __init__(self, llm_service=None, prompt_loader=None):
        """
        初始化Agent

        Args:
            llm_service: LLM服务实例（可选，默认使用全局单例）
            prompt_loader: Prompt加载器实例（可选，默认使用全局单例）
        """
        if llm_service is None:
            from app.services.llm_service import llm_service as default_llm_service
            self.llm_service = default_llm_service
        else:
            self.llm_service = llm_service

        if prompt_loader is None:
            from app.utils.prompt_loader import prompt_loader as default_prompt_loader
            self.prompt_loader = default_prompt_loader
        else:
            self.prompt_loader = prompt_loader

        logger.info(f"初始化Agent: {self.__class__.__name__}")

    @abstractmethod
    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理输入数据，返回结果

        Args:
            input_data: 输入数据字典

        Returns:
            结果字典

        Raises:
            NotImplementedError: 子类必须实现此方法
        """
        raise NotImplementedError("子类必须实现process方法")

    def _load_prompt(self, key: str, default: Optional[str] = None) -> str:
        """
        加载提示词

        Args:
            key: 提示词键名，如 "agent.example"
            default: 默认值（可选）

        Returns:
            提示词内容

        Raises:
            ValueError: 如果提示词不存在且未提供默认值
        """
        try:
            return self.prompt_loader.get(key, default)
        except ValueError as e:
            logger.error(f"加载提示词失败: {key} - {e}")
            raise

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None
    ) -> List[Dict[str, str]]:
        """
        构建LLM消息列表

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            history: 历史对话记录（可选）

        Returns:
            消息列表
        """
        messages = [
            {"role": "system", "content": system_prompt}
        ]

        # 添加历史对话
        if history:
            messages.extend(history)

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_prompt})

        return messages

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        model: str = "glm-4",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Any:
        """
        调用LLM服务

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            LLM响应对象
        """
        try:
            response = await self.llm_service.chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            if not response.success:
                error_msg = f"LLM调用失败: {response.error}"
                logger.error(error_msg)
                raise Exception(error_msg)

            return response

        except Exception as e:
            logger.error(f"LLM调用异常: {e}")
            raise

    def _validate_input(self, input_data: Dict[str, Any], required_fields: List[str]):
        """
        验证输入数据

        Args:
            input_data: 输入数据
            required_fields: 必需字段列表

        Raises:
            ValueError: 如果缺少必需字段
        """
        missing_fields = [field for field in required_fields if field not in input_data]

        if missing_fields:
            error_msg = f"缺少必需字段: {', '.join(missing_fields)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def get_agent_info(self) -> Dict[str, str]:
        """
        获取Agent信息

        Returns:
            包含Agent名称、描述等信息的字典
        """
        return {
            "name": self.__class__.__name__,
            "description": self.__class__.__doc__ or "无描述",
        }
