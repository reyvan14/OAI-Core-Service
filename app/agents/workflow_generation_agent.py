"""
工作流生成Agent - 通过AI对话自动生成工作流模板
支持用户用自然语言描述工作流需求，自动生成完整的工作流配置
"""

import logging
import json
import time
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import ValidationError, validator, BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import event
from app.services.llm_service import llm_service, LLMRequest, LLMProvider
from app.models.workflow import (
    WorkflowTemplateRequest, WorkflowNodeConfig, WorkflowTransition, WorkflowVariable,
    NodeType, AssigneeConfig, AssigneeType, NodeCondition, WorkflowGenerationHistory
)
from app.database import SessionLocal

logger = logging.getLogger(__name__)


class WorkflowGenerationAgent:
    """工作流生成Agent"""

    def __init__(self, llm_service_instance=None):
        self.llm_service = llm_service_instance if llm_service_instance else llm_service

    async def generate_workflow(self, description: str, user_id: str) -> Dict[str, Any]:
        """
        根据用户描述生成工作流配置

        Args:
            description: 工作流需求描述，如"创建一个包含经理审批和财务审批的费用报销流程"
            user_id: 用户ID

        Returns:
            包含完整工作流配置的字典
        """
        start_time = time.time()
        db = None
        history_id = str(uuid.uuid4())

        try:
            logger.info(f"开始生成工作流: user={user_id}, description={description[:50]}")

            # 构建提示词
            prompt = self._build_prompt(description)
            llm_start = time.time()

            # 调用LLM生成工作流配置
            llm_request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个工作流设计专家。根据用户需求生成完整的工作流配置JSON。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="glm-4",
                temperature=0.5,
                max_tokens=2000,
                provider=LLMProvider.ZHIPU
            )

            response = await self.llm_service.chat_completion(
                messages=llm_request.messages,
                model=llm_request.model,
                temperature=llm_request.temperature,
                max_tokens=llm_request.max_tokens
            )

            generation_time_ms = int((time.time() - llm_start) * 1000)

            if not response.success:
                raise Exception(f"LLM调用失败: {response.error}")

            # 解析LLM生成的工作流配置
            workflow_config = self._parse_workflow_config(response.content)

            # 保存生成历史到数据库
            db = None
            try:
                db = SessionLocal()
                history_record = WorkflowGenerationHistory(
                    id=history_id,
                    user_id=user_id,
                    description=description,
                    initial_workflow=workflow_config,
                    final_workflow=workflow_config,
                    refinement_rounds=0,
                    refinement_feedbacks=[],  # JSON字段：初始化为列表
                    status="generated",  # 使用常量
                    generation_time_ms=generation_time_ms,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    model_used=response.model,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(history_record)
                db.commit()
                logger.info(f"工作流生成历史保存成功: history_id={history_id}")
            except Exception as db_error:
                logger.warning(f"保存生成历史失败（不中断流程）: {str(db_error)}")
                # 不中断流程，继续返回结果
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

            logger.info(f"工作流生成成功: {workflow_config.get('name', 'Unknown')}")

            return {
                "success": True,
                "workflow": workflow_config,
                "generated_at": str(datetime.now()),
                "model": response.model,
                "history_id": history_id
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"工作流生成失败: {error_msg}", exc_info=True)
            return {
                "success": False,
                "error": f"AI工作流生成失败: {error_msg}",
                "workflow": None
            }

    def _build_prompt(self, description: str) -> str:
        """构建LLM提示词"""
        return f"""请根据以下工作流需求生成完整的工作流配置JSON。

工作流需求: {description}

请按照以下JSON格式生成工作流配置，务必返回有效的JSON（无其他文本）：

{{
    "name": "工作流名称",
    "description": "工作流描述",
    "category": "分类（财务/人事/采购/IT/行政/销售）",
    "start_node_id": "start",
    "end_node_ids": ["end"],
    "nodes": [
        {{
            "id": "start",
            "name": "开始",
            "description": "流程开始",
            "node_type": "start",
            "assignees": [],
            "is_required": true,
            "allow_parallel": false,
            "auto_approve": false
        }},
        {{
            "id": "approval_1",
            "name": "审批步骤名称",
            "description": "审批说明",
            "node_type": "approval",
            "assignees": [{{"type": "role", "value": "角色名称"}}],
            "is_required": true,
            "allow_parallel": false,
            "auto_approve": false
        }},
        {{
            "id": "end",
            "name": "完成",
            "description": "流程结束",
            "node_type": "end",
            "assignees": [],
            "is_required": true,
            "allow_parallel": false,
            "auto_approve": false
        }}
    ],
    "transitions": [
        {{"from_node": "start", "to_node": "approval_1", "condition": null, "action": null}},
        {{"from_node": "approval_1", "to_node": "end", "condition": null, "action": null}}
    ],
    "variables": [
        {{"name": "变量名", "type": "number/string/boolean", "description": "变量说明", "required": true}}
    ]
}}

要求：
- 至少包含3个节点（开始、至少1个审批步骤、结束）
- 生成2-4个合理的流程变量
- 所有节点ID必须唯一，且只包含字母数字和下划线
- 名称和描述使用中文
- 根据需求选择合适的分类"""

    def _parse_workflow_config(self, content: str) -> Dict[str, Any]:
        """
        解析LLM生成的工作流配置

        Args:
            content: LLM生成的JSON内容

        Returns:
            解析后的工作流配置字典
        """
        try:
            # 尝试从内容中提取JSON
            json_str = content.strip()

            # 如果LLM在JSON前后有其他文本，尝试提取JSON部分
            if not json_str.startswith("{"):
                start = json_str.find("{")
                end = json_str.rfind("}") + 1
                if start != -1 and end > start:
                    json_str = json_str[start:end]

            config = json.loads(json_str)

            # 验证必须的字段
            required_fields = ["name", "description", "category", "nodes", "transitions"]
            for field in required_fields:
                if field not in config:
                    raise ValueError(f"缺少必要字段: {field}")

            # 验证节点
            if not config.get("nodes") or len(config["nodes"]) < 2:
                raise ValueError("至少需要2个节点")

            # 设置默认值
            config["start_node_id"] = config.get("start_node_id", "start")
            config["end_node_ids"] = config.get("end_node_ids", ["end"])
            config["variables"] = config.get("variables", [])

            # 使用Pydantic进行深度验证
            self._validate_workflow_structure(config)

            logger.info(f"工作流配置解析成功: {config.get('name')}")

            return config

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {str(e)}, 内容预览: {content[:200]}", exc_info=True)
            raise ValueError(f"工作流配置JSON格式无效: {str(e)}")
        except ValueError as e:
            logger.error(f"工作流配置验证失败: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"工作流配置解析异常: {str(e)}", exc_info=True)
            raise

    def _validate_workflow_structure(self, config: Dict[str, Any]) -> None:
        """
        使用Pydantic进行工作流结构的深度验证

        Args:
            config: 工作流配置字典

        Raises:
            ValueError: 如果配置无效
        """
        try:
            # 验证基本类型
            if not isinstance(config.get("nodes"), list):
                raise ValueError("nodes 必须是数组类型")
            if not isinstance(config.get("transitions"), list):
                raise ValueError("transitions 必须是数组类型")

            # 收集所有node_id用于验证引用
            node_ids = set()

            # 验证每个节点
            for idx, node in enumerate(config["nodes"]):
                if not isinstance(node, dict):
                    raise ValueError(f"节点 {idx} 必须是字典类型")

                # 验证必须的节点字段
                if not node.get("id"):
                    raise ValueError(f"节点 {idx} 缺少 id 字段")
                if not node.get("name"):
                    raise ValueError(f"节点 {idx} 缺少 name 字段")
                if not node.get("node_type"):
                    raise ValueError(f"节点 {idx} 缺少 node_type 字段")

                node_id = node["id"]

                # 检查node_id唯一性
                if node_id in node_ids:
                    raise ValueError(f"节点ID {node_id} 重复")
                node_ids.add(node_id)

                # 验证node_type是有效的枚举值
                valid_types = [nt.value for nt in NodeType]
                if node["node_type"] not in valid_types:
                    raise ValueError(f"节点 {node_id} 的 node_type '{node['node_type']}' 无效，必须是 {valid_types} 之一")

                # 验证assignees结构
                assignees = node.get("assignees", [])
                if not isinstance(assignees, list):
                    raise ValueError(f"节点 {node_id} 的 assignees 必须是数组")

                for assignee_idx, assignee in enumerate(assignees):
                    if not isinstance(assignee, dict):
                        raise ValueError(f"节点 {node_id} 的 assignee {assignee_idx} 必须是字典")
                    if "type" not in assignee or "value" not in assignee:
                        raise ValueError(f"节点 {node_id} 的 assignee {assignee_idx} 缺少 type 或 value 字段")

                    # 验证assignee type
                    valid_assignee_types = [at.value for at in AssigneeType]
                    if assignee["type"] not in valid_assignee_types:
                        raise ValueError(f"节点 {node_id} 的 assignee type '{assignee['type']}' 无效，必须是 {valid_assignee_types} 之一")

                # 验证conditions和actions是数组
                if node.get("conditions") and not isinstance(node["conditions"], list):
                    raise ValueError(f"节点 {node_id} 的 conditions 必须是数组")
                if node.get("actions") and not isinstance(node["actions"], list):
                    raise ValueError(f"节点 {node_id} 的 actions 必须是数组")

            # 验证transitions中的节点引用
            for idx, transition in enumerate(config["transitions"]):
                if not isinstance(transition, dict):
                    raise ValueError(f"转换 {idx} 必须是字典类型")

                from_node = transition.get("from_node")
                to_node = transition.get("to_node")

                if not from_node:
                    raise ValueError(f"转换 {idx} 缺少 from_node 字段")
                if not to_node:
                    raise ValueError(f"转换 {idx} 缺少 to_node 字段")

                # 验证from_node和to_node都在node_ids中
                if from_node not in node_ids:
                    raise ValueError(f"转换 {idx} 的 from_node '{from_node}' 不存在于节点列表中")
                if to_node not in node_ids:
                    raise ValueError(f"转换 {idx} 的 to_node '{to_node}' 不存在于节点列表中")

            # 验证start_node_id和end_node_ids
            if config.get("start_node_id") not in node_ids:
                raise ValueError(f"start_node_id '{config.get('start_node_id')}' 不存在于节点列表中")

            for end_node_id in config.get("end_node_ids", []):
                if end_node_id not in node_ids:
                    raise ValueError(f"end_node_ids 中的 '{end_node_id}' 不存在于节点列表中")

            # 验证variables类型
            if config.get("variables") and not isinstance(config["variables"], list):
                raise ValueError("variables 必须是数组类型")

            logger.info("✅ 工作流结构验证成功")

        except ValueError as e:
            logger.error(f"工作流结构验证失败: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"工作流结构验证异常: {str(e)}", exc_info=True)
            raise ValueError(f"工作流验证异常: {str(e)}")

    async def refine_workflow(
        self,
        initial_config: Dict[str, Any],
        feedback: str,
        user_id: str = None,
        history_id: str = None
    ) -> Dict[str, Any]:
        """
        根据用户反馈调整工作流配置

        Args:
            initial_config: 初始工作流配置
            feedback: 用户反馈
            user_id: 用户ID（用于更新历史）
            history_id: 历史记录ID（用于更新对应的历史记录）

        Returns:
            调整后的工作流配置
        """
        start_time = time.time()
        db = None

        try:
            logger.info(f"开始调整工作流: feedback={feedback[:50]}, history_id={history_id}")
            llm_start = time.time()

            prompt = f"""已有工作流配置：
{json.dumps(initial_config, ensure_ascii=False, indent=2)}

用户反馈: {feedback}

请根据用户反馈调整工作流配置，返回完整的修改后的JSON（只返回JSON，无其他文本）。"""

            llm_request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": "你是工作流设计专家，能根据反馈调整工作流配置。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="glm-4",
                temperature=0.5,
                max_tokens=2000,
                provider=LLMProvider.ZHIPU
            )

            response = await self.llm_service.chat_completion(
                messages=llm_request.messages,
                model=llm_request.model,
                temperature=llm_request.temperature,
                max_tokens=llm_request.max_tokens
            )

            generation_time_ms = int((time.time() - llm_start) * 1000)

            if not response.success:
                raise Exception(f"LLM调用失败: {response.error}")

            refined_config = self._parse_workflow_config(response.content)

            # 更新历史记录（如果提供了history_id）
            db = None
            if history_id and user_id:
                try:
                    db = SessionLocal()
                    history = db.query(WorkflowGenerationHistory).filter(
                        WorkflowGenerationHistory.id == history_id,
                        WorkflowGenerationHistory.user_id == user_id
                    ).first()

                    if history:
                        # 更新历史记录
                        history.final_workflow = refined_config
                        history.refinement_rounds = (history.refinement_rounds or 0) + 1

                        # 添加反馈到列表（重新赋值确保SQLAlchemy检测到JSON字段修改）
                        current_feedbacks = history.refinement_feedbacks or []
                        current_feedbacks.append({
                            "round": history.refinement_rounds,
                            "feedback": feedback,
                            "timestamp": str(datetime.now())
                        })
                        history.refinement_feedbacks = current_feedbacks  # 重新赋值

                        history.updated_at = datetime.now()
                        db.commit()
                        logger.info(f"工作流优化历史更新成功: history_id={history_id}, round={history.refinement_rounds}")
                    else:
                        logger.warning(f"未找到对应的历史记录: history_id={history_id}")
                except Exception as db_error:
                    logger.warning(f"更新优化历史失败（不中断流程）: {str(db_error)}")
                    # 不中断流程
                finally:
                    if db:
                        try:
                            db.close()
                        except Exception:
                            pass

            logger.info("工作流调整成功")

            return {
                "success": True,
                "workflow": refined_config
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"工作流调整失败: {error_msg}", exc_info=True)
            return {
                "success": False,
                "error": f"AI工作流优化失败: {error_msg}"
            }
