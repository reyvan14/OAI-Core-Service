"""
智谱AI客户端服务
"""
import json
import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ZhipuAIClient:
    """智谱AI API客户端"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/"

    def _generate_jwt(self) -> str:
        """生成智谱AI API JWT Token"""
        try:
            # 尝试使用官方SDK
            try:
                from zhipuai import ZhipuAI
                return self.api_key
            except ImportError:
                # SDK不可用时使用手动JWT生成
                import jwt
                import time

                try:
                    api_key, secret = self.api_key.split(".")
                except ValueError:
                    raise ValueError("Invalid API key format")

                payload = {
                    "api_key": api_key,
                    "exp": int(time.time() * 1000) + 3600 * 1000,
                    "timestamp": int(time.time() * 1000)
                }

                return jwt.encode(
                    payload,
                    secret,
                    algorithm="HS256",
                    headers={"alg": "HS256", "sign_type": "SIGN"}
                )
        except Exception as e:
            logger.error(f"生成JWT失败: {e}")
            raise

    def chat(self, messages: List[Dict[str, str]], model: str = "glm-4.7") -> Dict[str, Any]:
        """调用智谱AI聊天接口

        Args:
            messages: 对话消息列表
            model: 模型名称，默认 glm-4-plus（关闭thinking模式以获得更快响应）
        """
        # 输入验证
        if not messages or not isinstance(messages, list):
            return {
                "success": False,
                "error": "Invalid messages format",
                "error_code": "INVALID_INPUT"
            }

        if not any(msg.get("content") for msg in messages):
            return {
                "success": False,
                "error": "Empty message content",
                "error_code": "EMPTY_CONTENT"
            }

        try:
            # 尝试使用SDK
            try:
                from zhipuai import ZhipuAI
                client = ZhipuAI(api_key=self.api_key)

                # 构建请求参数
                request_params = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 2000,
                }

                # 对于glm-4.7模型，显式关闭thinking模式以获得更快响应
                if "4.7" in model:
                    request_params["thinking"] = {
                        "type": "disabled",
                        "clear_thinking": True
                    }

                response = client.chat.completions.create(**request_params)

                content = response.choices[0].message.content
                if not content or not content.strip():
                    return {
                        "success": False,
                        "error": "Empty AI response",
                        "error_code": "EMPTY_RESPONSE"
                    }

                return {
                    "success": True,
                    "content": content.strip(),
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    },
                    "model": model
                }
            except ImportError:
                # SDK不可用，使用HTTP请求
                jwt_token = self._generate_jwt()

                headers = {
                    "Authorization": f"Bearer {jwt_token}",
                    "Content-Type": "application/json"
                }

                data = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 2000,
                    "stream": False
                }

                # 对于glm-4.7模型，显式关闭thinking模式
                if "4.7" in model:
                    data["thinking"] = {
                        "type": "disabled",
                        "clear_thinking": True
                    }

                response = requests.post(
                    f"{self.base_url}chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30
                )

                response.raise_for_status()
                result = response.json()

                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if not content or not content.strip():
                        return {
                            "success": False,
                            "error": "Empty AI response",
                            "error_code": "EMPTY_RESPONSE"
                        }

                    return {
                        "success": True,
                        "content": content.strip(),
                        "usage": result.get("usage", {}),
                        "model": model
                    }
                else:
                    return {
                        "success": False,
                        "error": "Invalid response format",
                        "error_code": "INVALID_FORMAT",
                        "response": result
                    }

        except Exception as e:
            logger.error(f"智谱AI调用失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def chat_stream(self, messages: List[Dict[str, str]], model: str = "glm-4.7"):
        """流式调用智谱AI聊天接口"""
        # 输入验证
        if not messages or not isinstance(messages, list):
            yield json.dumps({"error": "Invalid messages format"}) + "\n"
            return

        try:
            # 尝试使用SDK
            try:
                from zhipuai import ZhipuAI
                client = ZhipuAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    top_p=0.9,
                    max_tokens=2000,
                    stream=True
                )

                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, 'content') and delta.content:
                            yield json.dumps({
                                "content": delta.content,
                                "done": False
                            }, ensure_ascii=False) + "\n"

                # 发送结束标记
                yield json.dumps({"done": True}) + "\n"

            except ImportError:
                # SDK不可用，使用HTTP请求
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                data = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 2000,
                    "stream": True
                }

                response = requests.post(
                    f"{self.base_url}chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30,
                    stream=True
                )

                response.raise_for_status()

                for line in response.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                            if data_str.strip() == '[DONE]':
                                yield json.dumps({"done": True}) + "\n"
                                break

                            try:
                                data_json = json.loads(data_str)
                                if 'choices' in data_json and len(data_json['choices']) > 0:
                                    delta = data_json['choices'][0].get('delta', {})
                                    content = delta.get('content', '')
                                    if content:
                                        yield json.dumps({
                                            "content": content,
                                            "done": False
                                        }, ensure_ascii=False) + "\n"
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            logger.error(f"智谱AI流式调用失败: {e}")
            yield json.dumps({"error": str(e), "done": True}) + "\n"
