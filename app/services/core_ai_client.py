"""
核心AI服务客户端
负责将请求转发到阿里云核心服务器
"""
import logging
import httpx
from typing import Dict, Any, List, Optional, AsyncIterator
from app.core.config import settings

logger = logging.getLogger(__name__)


class CoreAIClient:
    """核心AI服务客户端"""

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or settings.CORE_AI_URL
        self.api_key = api_key or settings.CORE_AI_KEY
        self.timeout = 90.0  # 增加到90秒以适应模板匹配API（实测需要45秒）

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "glm-4",
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        发送聊天请求到核心服务器

        Args:
            messages: 消息列表
            model: 模型名称
            stream: 是否流式输出

        Returns:
            AI响应结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/chat",
                    headers=self._get_headers(),
                    json={
                        "messages": messages,
                        "model": model,
                        "stream": stream
                    }
                )
                response.raise_for_status()
                result = response.json()

                # 适配核心服务器返回格式: {"success":true,"data":{"content":...}}
                if result.get("success") and "data" in result:
                    data = result["data"]
                    return {
                        "success": True,
                        "content": data.get("content", ""),
                        "model": data.get("model", model),
                        "usage": data.get("usage", {})
                    }
                return result

        except httpx.HTTPStatusError as e:
            logger.error(f"核心服务器HTTP错误: {e.response.status_code} - {e.response.text}")
            return {
                "success": False,
                "error": f"核心服务器返回错误: {e.response.status_code}"
            }
        except httpx.RequestError as e:
            logger.error(f"核心服务器请求失败: {str(e)}")
            return {
                "success": False,
                "error": f"无法连接到核心服务器: {str(e)}"
            }
        except Exception as e:
            logger.error(f"核心服务器调用异常: {str(e)}")
            return {
                "success": False,
                "error": f"核心服务器调用失败: {str(e)}"
            }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = "glm-4"
    ) -> AsyncIterator[str]:
        """
        流式聊天请求

        Args:
            messages: 消息列表
            model: 模型名称

        Yields:
            流式响应数据
        """
        try:
            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/ai/chat/stream",
                    headers=self._get_headers(),
                    json={
                        "messages": messages,
                        "model": model
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            yield line

        except Exception as e:
            logger.error(f"核心服务器流式调用失败: {str(e)}")
            yield f'{{"error": "核心服务器调用失败: {str(e)}"}}'

    async def analyze_intent(self, content: str) -> Dict[str, Any]:
        """
        分析用户意图

        Args:
            content: 用户输入内容

        Returns:
            意图分析结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/intent",
                    headers=self._get_headers(),
                    json={"content": content}
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"意图分析失败: {str(e)}")
            return {
                "intent": "chat",
                "workflow_type": None,
                "confidence": 0.0,
                "reasoning": f"核心服务器调用失败: {str(e)}"
            }

    async def generate_workflow(
        self,
        description: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        生成工作流

        Args:
            description: 工作流描述
            user_id: 用户ID

        Returns:
            工作流生成结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/workflow/generate",
                    headers=self._get_headers(),
                    json={
                        "description": description,
                        "user_id": user_id
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"工作流生成失败: {str(e)}")
            raise Exception(f"核心服务器调用失败: {str(e)}")

    async def extract_fields(
        self,
        user_response: str,
        missing_fields: List[str],
        template_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        提取字段值

        Args:
            user_response: 用户回复
            missing_fields: 缺失字段列表
            template_data: 模板数据

        Returns:
            提取的字段值
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/fields/extract",
                    headers=self._get_headers(),
                    json={
                        "user_response": user_response,
                        "missing_fields": missing_fields,
                        "template_data": template_data
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"字段提取失败: {str(e)}")
            return {}

    async def match_workflow_template(
        self,
        description: str,
        workflow_type: Optional[str],
        templates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        匹配工作流模板并提取变量

        Args:
            description: 用户描述
            workflow_type: 工作流类型
            templates: 可用模板列表

        Returns:
            匹配结果
        """
        try:
            request_data = {
                "description": description,
                "workflow_type": workflow_type,
                "templates": templates
            }

            # 调试日志：记录请求数据
            import json as json_module
            request_json = json_module.dumps(request_data, ensure_ascii=False, default=str)
            request_size_kb = len(request_json.encode('utf-8')) / 1024

            logger.info(f"🔵 [模板匹配] 请求核心服务器")
            logger.info(f"  描述: {description}")
            logger.info(f"  类型: {workflow_type}")
            logger.info(f"  模板数量: {len(templates)}")
            logger.info(f"  模板ID列表: {[t.get('id') for t in templates]}")
            logger.info(f"  📦 请求数据大小: {request_size_kb:.2f} KB")

            # 记录每个模板的variables字段数量和大小
            for tmpl in templates:
                var_list = tmpl.get('variables', [])
                var_count = len(var_list)
                if var_list:
                    first_var_keys = list(var_list[0].keys()) if var_list else []
                    logger.info(f"    - {tmpl.get('id')}: {var_count} 个变量, 字段: {first_var_keys}")

            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/workflow/match",
                    headers=self._get_headers(),
                    json=request_data
                )
                response.raise_for_status()
                result = response.json()

                # 调试日志：记录响应数据
                logger.info(f"✅ [模板匹配] 核心服务器响应: {result}")

                # 转换为客户端期望的格式
                return {
                    "success": True,
                    "template_id": result.get("matched_template_id"),
                    "variables": result.get("extracted_variables", {}),
                    "confidence": result.get("confidence"),
                    "reason": result.get("reasoning", "")
                }

        except Exception as e:
            logger.error(f"❌ [模板匹配] 失败: {str(e)}")
            raise Exception(f"核心服务器调用失败: {str(e)}")

    async def refine_workflow(
        self,
        workflow: Dict[str, Any],
        feedback: str,
        user_id: str,
        history_id: str = None
    ) -> Dict[str, Any]:
        """
        优化工作流

        Args:
            workflow: 当前工作流配置
            feedback: 用户反馈
            user_id: 用户ID
            history_id: 历史记录ID

        Returns:
            优化后的工作流
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/workflow/refine",
                    headers=self._get_headers(),
                    json={
                        "workflow": workflow,
                        "feedback": feedback,
                        "user_id": user_id,
                        "history_id": history_id
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"工作流优化失败: {str(e)}")
            raise Exception(f"核心服务器调用失败: {str(e)}")

    async def fill_form(
        self,
        message: str,
        form_type: str = None,
        session_id: str = None,
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        智能表单填写

        Args:
            message: 用户输入
            form_type: 表单类型
            session_id: 会话ID
            user_id: 用户ID

        Returns:
            表单填写结果
        """
        url = f"{self.base_url}/ai/forms/fill"
        logger.info(f"🔵 [CoreAIClient] fill_form called: message={message[:50]}, form_type={form_type}")
        logger.info(f"🌐 [CoreAIClient] Request URL: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json={
                        "message": message,
                        "form_type": form_type
                    }
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✅ [CoreAIClient] Response: {result}")
                return result

        except Exception as e:
            logger.error(f"表单填写失败: {str(e)}")
            return {"form_type": form_type, "extracted_fields": {}, "confidence": 0.0}

    async def validate_form(
        self,
        form_data: Dict[str, Any],
        form_type: str
    ) -> Dict[str, Any]:
        """
        表单验证

        Args:
            form_data: 表单数据
            form_type: 表单类型

        Returns:
            验证结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/forms/validate",
                    headers=self._get_headers(),
                    json={
                        "form_data": form_data,
                        "form_type": form_type
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"表单验证失败: {str(e)}")
            return {"is_valid": True, "errors": [], "warnings": []}

    async def check_form_compliance(
        self,
        form_data: Dict[str, Any],
        business_rules: List[str]
    ) -> Dict[str, Any]:
        """
        表单合规检查

        Args:
            form_data: 表单数据
            business_rules: 业务规则列表

        Returns:
            合规检查结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/forms/compliance",
                    headers=self._get_headers(),
                    json={
                        "form_data": form_data,
                        "business_rules": business_rules
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"合规检查失败: {str(e)}")
            return {"is_compliant": True, "violations": [], "suggestions": []}

    async def submit_approval(
        self,
        approval_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        审批提交分析

        Args:
            approval_data: 审批数据

        Returns:
            分析结果
        """
        logger.info(f"🔵 [CoreAIClient] submit_approval called: data={approval_data}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/approvals/submit",
                    headers=self._get_headers(),
                    json={"approval_data": approval_data}
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"审批提交分析失败: {str(e)}")
            return {"suggested_approvers": [], "risk_level": "medium"}

    async def analyze_approval(
        self,
        approval_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        审批智能分析

        Args:
            approval_id: 审批ID
            context: 审批上下文

        Returns:
            分析结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/approvals/analyze",
                    headers=self._get_headers(),
                    json={
                        "approval_id": approval_id,
                        "context": context
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"审批分析失败: {str(e)}")
            return {"decision_suggestion": "review", "confidence": 0.5}

    async def analyze_pain_points(
        self,
        feedback_data: List[Dict[str, Any]],
        time_range: str = "30天"
    ) -> Dict[str, Any]:
        """
        痛点分析

        Args:
            feedback_data: 反馈数据
            time_range: 时间范围

        Returns:
            痛点分析结果
        """
        logger.info(f"🔵 [CoreAIClient] analyze_pain_points called: time_range={time_range}, data_count={len(feedback_data)}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/analytics/pain-points",
                    headers=self._get_headers(),
                    json={
                        "feedback_data": feedback_data,
                        "time_range": time_range
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"痛点分析失败: {str(e)}")
            return {"pain_points": [], "top_issues": []}

    async def custom_analytics_query(
        self,
        query: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        自定义数据查询分析

        Args:
            query: 查询语句
            data: 数据集

        Returns:
            分析结果
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.post(
                    f"{self.base_url}/ai/analytics/query",
                    headers=self._get_headers(),
                    json={
                        "query": query,
                        "data": data
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"自定义分析失败: {str(e)}")
            return {"insights": [], "metrics": {}, "summary": "分析失败"}


# 全局实例
core_ai_client = CoreAIClient()
