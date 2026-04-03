"""
补充缺失的API端点 - 将这些代码添加到core_server.py中
"""

import json
from fastapi.responses import StreamingResponse
from zhipuai import ZhipuAI


# ==================== 补充API端点 ====================

@app.post("/ai/chat/stream")
async def ai_chat_stream(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    流式聊天

    请求格式：
    {
        "messages": [{"role": "user", "content": "你好"}],
        "model": "glm-4"
    }

    返回：Server-Sent Events流
    """
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "glm-4")

    logger.info(f"💬🌊 {customer_id} 请求流式对话: {len(messages)}条消息")

    async def generate():
        """异步生成器，逐块返回AI响应"""
        try:
            client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7
            )

            total_content = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    total_content += content
                    # SSE格式：data: <content>\n\n
                    yield f"data: {content}\n\n"

            # 流式结束标记
            yield "data: [DONE]\n\n"

            # 记录使用量（估算）
            await record_usage(customer_id, "chat_stream", len(total_content) * 2)

        except Exception as e:
            logger.error(f"流式聊天失败: {e}", exc_info=True)
            error_msg = json.dumps({"error": str(e)})
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用nginx缓冲
        }
    )


@app.post("/ai/intent")
async def analyze_intent(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    意图识别

    分析用户输入，判断是创建工作流、提交申请还是普通聊天

    请求格式：
    {
        "content": "我要报销3000元"
    }

    返回格式：
    {
        "intent": "submit_application" | "create_template" | "chat",
        "workflow_type": "报销" | "请假" | null,
        "confidence": 0.0-1.0,
        "reasoning": "判断理由"
    }
    """
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    content = body.get("content", "")

    if not content:
        raise HTTPException(400, "content不能为空")

    logger.info(f"🔍 {customer_id} 请求意图识别: {content[:50]}...")

    # 构建意图识别提示词
    system_prompt = """你是一个意图识别专家。分析用户输入，判断用户意图。

可能的意图类型：
1. **submit_application** - 用户想提交申请/审批
   - 关键词：报销、请假、采购、出差、加班、申请等
   - 示例："我要报销3000元"、"我想请3天假"

2. **create_template** - 用户想创建新的工作流模板
   - 关键词：创建模板、设计流程、新建工作流等
   - 示例："帮我创建一个报销流程"、"设计一个请假审批流程"

3. **chat** - 普通对话/咨询
   - 不涉及具体业务操作
   - 示例："你好"、"报销流程是什么样的？"

如果是submit_application，还需识别具体的工作流类型：
- 报销、请假、采购、出差、加班、培训、转正、离职等

返回JSON格式（不要包含markdown代码块标记）：
{
    "intent": "submit_application",
    "workflow_type": "报销",
    "confidence": 0.95,
    "reasoning": "用户明确提到了报销金额，属于提交申请"
}
"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户输入：{content}"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()

        # 清理可能的markdown代码块标记
        if llm_output.startswith("```json"):
            llm_output = llm_output[7:]
        if llm_output.startswith("```"):
            llm_output = llm_output[3:]
        if llm_output.endswith("```"):
            llm_output = llm_output[:-3]
        llm_output = llm_output.strip()

        # 解析LLM返回的JSON
        result = json.loads(llm_output)

        # 验证返回格式
        if "intent" not in result:
            raise ValueError("返回结果缺少intent字段")

        logger.info(f"✅ 意图识别结果: {result['intent']} (置信度: {result.get('confidence', 0)})")

        await record_usage(customer_id, "intent", response.usage.total_tokens)

        return result

    except json.JSONDecodeError as e:
        logger.error(f"意图识别JSON解析失败: {e}, LLM输出: {llm_output}")
        # 降级策略：返回默认意图
        return {
            "intent": "chat",
            "workflow_type": None,
            "confidence": 0.0,
            "reasoning": f"JSON解析失败: {str(e)}"
        }
    except Exception as e:
        logger.error(f"意图识别失败: {e}", exc_info=True)
        return {
            "intent": "chat",
            "workflow_type": None,
            "confidence": 0.0,
            "reasoning": f"识别失败: {str(e)}"
        }


@app.post("/ai/fields/extract")
async def extract_fields(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    字段提取

    从用户输入中提取表单字段值

    请求格式：
    {
        "user_response": "我要报销3000元，用于购买办公用品",
        "missing_fields": ["amount", "expense_type", "reason"],
        "template_data": {
            "name": "报销申请",
            "fields": [...]
        }
    }

    返回格式：
    {
        "amount": 3000,
        "expense_type": "办公用品",
        "reason": "购买办公用品"
    }
    """
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    user_response = body.get("user_response", "")
    missing_fields = body.get("missing_fields", [])
    template_data = body.get("template_data", {})

    if not user_response or not missing_fields:
        raise HTTPException(400, "user_response和missing_fields不能为空")

    logger.info(f"📝 {customer_id} 请求字段提取: {len(missing_fields)}个字段")

    # 构建字段提取提示词
    template_info = json.dumps(template_data, ensure_ascii=False, indent=2)
    system_prompt = f"""你是一个智能表单填写助手。从用户输入中提取字段值。

需要提取的字段：{', '.join(missing_fields)}

模板信息：
{template_info}

任务：
1. 仔细分析用户输入
2. 提取需要的字段值
3. 如果某个字段无法从用户输入中提取，则不包含该字段
4. 返回纯JSON格式（不要包含markdown代码块标记）

示例：
用户输入："我要报销3000元，用于购买办公用品"
需要字段：["amount", "expense_type", "reason"]
返回：
{{
    "amount": 3000,
    "expense_type": "办公用品",
    "reason": "购买办公用品"
}}

注意：
- 数字类型的字段要返回数字，不要返回字符串
- 日期格式统一为YYYY-MM-DD
- 金额单位统一为元
"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_response}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()

        # 清理markdown代码块标记
        if llm_output.startswith("```json"):
            llm_output = llm_output[7:]
        if llm_output.startswith("```"):
            llm_output = llm_output[3:]
        if llm_output.endswith("```"):
            llm_output = llm_output[:-3]
        llm_output = llm_output.strip()

        # 解析LLM返回的JSON
        extracted_fields = json.loads(llm_output)

        logger.info(f"✅ 提取到字段: {list(extracted_fields.keys())}")

        await record_usage(customer_id, "fields_extract", response.usage.total_tokens)

        return extracted_fields

    except json.JSONDecodeError as e:
        logger.error(f"字段提取JSON解析失败: {e}, LLM输出: {llm_output}")
        return {}
    except Exception as e:
        logger.error(f"字段提取失败: {e}", exc_info=True)
        return {}


@app.post("/ai/workflow/match")
async def match_workflow_template(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    工作流模板匹配

    根据用户描述匹配最合适的工作流模板并提取变量

    请求格式：
    {
        "description": "我要报销3000元差旅费",
        "workflow_type": "报销",
        "templates": [
            {
                "id": "tpl_001",
                "name": "报销申请",
                "description": "用于报销费用",
                "variables": ["amount", "expense_type"]
            },
            {
                "id": "tpl_002",
                "name": "差旅报销",
                "description": "差旅费用报销",
                "variables": ["amount", "destination"]
            }
        ]
    }

    返回格式：
    {
        "matched_template_id": "tpl_002",
        "confidence": 0.92,
        "extracted_variables": {
            "amount": 3000
        },
        "reasoning": "用户提到了差旅费，更匹配差旅报销模板"
    }
    """
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    workflow_type = body.get("workflow_type")
    templates = body.get("templates", [])

    if not description or not templates:
        raise HTTPException(400, "description和templates不能为空")

    logger.info(f"🔄 {customer_id} 请求模板匹配: {workflow_type}, {len(templates)}个候选模板")

    # 构建模板匹配提示词
    templates_str = json.dumps(templates, ensure_ascii=False, indent=2)
    system_prompt = f"""你是一个工作流模板匹配专家。根据用户描述，从候选模板中选择最匹配的一个。

可用模板列表：
{templates_str}

分析步骤：
1. 理解用户的需求描述
2. 对比每个模板的名称、描述和适用场景
3. 选择最匹配的模板
4. 尝试从用户描述中提取模板所需的变量值

返回纯JSON格式（不要包含markdown代码块标记）：
{{
    "matched_template_id": "模板ID",
    "confidence": 0.0-1.0（置信度，0-1之间的小数）,
    "extracted_variables": {{"变量名": "值"}},
    "reasoning": "匹配理由"
}}

注意：
- matched_template_id必须是候选模板中的一个
- confidence在0-1之间
- extracted_variables中的值要符合变量类型（数字就是数字，不要加引号）
"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户描述：{description}\n工作流类型：{workflow_type or '未指定'}"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()

        # 清理markdown代码块标记
        if llm_output.startswith("```json"):
            llm_output = llm_output[7:]
        if llm_output.startswith("```"):
            llm_output = llm_output[3:]
        if llm_output.endswith("```"):
            llm_output = llm_output[:-3]
        llm_output = llm_output.strip()

        # 解析LLM返回的JSON
        match_result = json.loads(llm_output)

        # 验证返回格式
        if "matched_template_id" not in match_result:
            raise ValueError("返回结果缺少matched_template_id字段")

        logger.info(f"✅ 匹配到模板: {match_result['matched_template_id']} (置信度: {match_result.get('confidence', 0)})")

        await record_usage(customer_id, "workflow_match", response.usage.total_tokens)

        return match_result

    except json.JSONDecodeError as e:
        logger.error(f"模板匹配JSON解析失败: {e}, LLM输出: {llm_output}")
        # 降级策略：返回第一个模板
        return {
            "matched_template_id": templates[0]["id"],
            "confidence": 0.5,
            "extracted_variables": {},
            "reasoning": f"JSON解析失败，返回默认模板: {str(e)}"
        }
    except Exception as e:
        logger.error(f"模板匹配失败: {e}", exc_info=True)
        # 降级策略
        if templates:
            return {
                "matched_template_id": templates[0]["id"],
                "confidence": 0.5,
                "extracted_variables": {},
                "reasoning": f"匹配失败，返回默认模板: {str(e)}"
            }
        raise HTTPException(500, f"模板匹配失败: {str(e)}")


# ==================== 完善TODO的工作流生成API ====================
@app.post("/ai/workflow/generate")
async def workflow_generate(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    智能工作流生成（完整实现）

    请求格式：
    {
        "description": "创建一个请假审批流程，需要部门主管和HR审批",
        "user_id": "user_123"
    }

    返回格式：
    {
        "success": true,
        "workflow_config": {
            "name": "请假审批流程",
            "description": "...",
            "nodes": [...],
            "transitions": [...],
            "variables": [...]
        }
    }
    """
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    user_id = body.get("user_id", "")

    if not description:
        raise HTTPException(400, "description不能为空")

    logger.info(f"🔄 {customer_id} 请求工作流生成: {description[:50]}...")

    # 加载工作流生成提示词（如果有prompts文件）
    try:
        with open("prompts/agents/workflow_generation.txt", "r", encoding="utf-8") as f:
            workflow_prompt_template = f.read()
    except:
        # 如果没有文件，使用内置提示词
        workflow_prompt_template = """你是一个工作流设计专家。根据用户需求生成完整的工作流配置JSON。

工作流配置格式：
{
    "name": "工作流名称",
    "description": "工作流描述",
    "category": "报销/请假/采购等",
    "nodes": [
        {
            "id": "node_1",
            "name": "提交申请",
            "type": "start",
            "assignee": {"type": "initiator"}
        },
        {
            "id": "node_2",
            "name": "部门主管审批",
            "type": "approval",
            "assignee": {"type": "role", "value": "department_manager"}
        },
        {
            "id": "node_3",
            "name": "结束",
            "type": "end"
        }
    ],
    "transitions": [
        {
            "from": "node_1",
            "to": "node_2",
            "condition": null
        },
        {
            "from": "node_2",
            "to": "node_3",
            "condition": {"type": "approved"}
        }
    ],
    "variables": [
        {
            "name": "reason",
            "label": "请假原因",
            "type": "text",
            "required": true
        }
    ]
}

返回纯JSON，不要包含markdown代码块标记。
"""

    system_prompt = workflow_prompt_template

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户需求：{description}"}
            ],
            temperature=0.5,
            max_tokens=2000
        )

        llm_output = response.choices[0].message.content.strip()

        # 清理markdown代码块标记
        if llm_output.startswith("```json"):
            llm_output = llm_output[7:]
        if llm_output.startswith("```"):
            llm_output = llm_output[3:]
        if llm_output.endswith("```"):
            llm_output = llm_output[:-3]
        llm_output = llm_output.strip()

        # 解析工作流配置
        workflow_config = json.loads(llm_output)

        # 验证必需字段
        required_fields = ["name", "nodes", "transitions"]
        for field in required_fields:
            if field not in workflow_config:
                raise ValueError(f"缺少必需字段: {field}")

        logger.info(f"✅ 工作流生成成功: {workflow_config['name']}")

        await record_usage(customer_id, "workflow_generate", response.usage.total_tokens)

        return {
            "success": True,
            "workflow_config": workflow_config
        }

    except json.JSONDecodeError as e:
        logger.error(f"工作流生成JSON解析失败: {e}, LLM输出: {llm_output[:200]}")
        raise HTTPException(500, f"工作流配置解析失败: {str(e)}")
    except Exception as e:
        logger.error(f"工作流生成失败: {e}", exc_info=True)
        raise HTTPException(500, f"工作流生成失败: {str(e)}")
