# AI-OA核心服务器 - 缺失API补充清单

## 📋 现状分析

### ✅ 已实现的API
1. `/health` - GET - 健康检查
2. `/ai/chat` - POST - 智能对话（完整实现）
3. `/ai/form/fill` - POST - 表单填写（TODO）
4. `/ai/approve` - POST - 审批决策（TODO）
5. `/ai/workflow/generate` - POST - 工作流生成（TODO）
6. `/ai/analytics` - POST - 数据分析（TODO）

### ❌ 缺失的API（客户端需要但服务器未实现）
1. ❌ `/ai/chat/stream` - POST - 流式聊天
2. ❌ `/ai/intent` - POST - 意图识别
3. ❌ `/ai/fields/extract` - POST - 字段提取
4. ❌ `/ai/workflow/match` - POST - 模板匹配

### ⚠️ 问题
- **agents目录为空** - 7个核心Agent代码未迁移到核心服务器
- **提示词不完整** - 只有3个txt文件（example, workflow_generation, workflow_refinement）
- **部分API只有框架** - 标记为TODO，未实际实现

---

## 🔧 需要补充的API端点

### 1. 流式聊天 `/ai/chat/stream`

**用途**：实时流式返回AI响应，提升用户体验

**实现方式**：
```python
from fastapi.responses import StreamingResponse
from zhipuai import ZhipuAI

@app.post("/ai/chat/stream")
async def ai_chat_stream(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """流式聊天"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "glm-4")

    logger.info(f"💬 {customer_id} 请求流式对话")

    async def generate():
        try:
            client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True
            )

            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield f"data: {chunk.choices[0].delta.content}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式聊天失败: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )
```

---

### 2. 意图识别 `/ai/intent`

**用途**：分析用户输入，判断是创建工作流、提交申请还是普通聊天

**实现方式**：
```python
@app.post("/ai/intent")
async def analyze_intent(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    意图识别

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

    logger.info(f"🔍 {customer_id} 请求意图识别: {content[:50]}...")

    # 构建意图识别提示词
    system_prompt = """你是一个意图识别专家。分析用户输入，判断用户意图。

可能的意图类型：
1. submit_application - 用户想提交申请/审批（如报销、请假、采购等）
2. create_template - 用户想创建新的工作流模板
3. chat - 普通对话/咨询

如果是submit_application，还需识别具体的工作流类型：报销、请假、采购、出差、加班等。

返回JSON格式：
{
    "intent": "submit_application",
    "workflow_type": "报销",
    "confidence": 0.95,
    "reasoning": "用户明确提到了报销金额"
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

        # 解析LLM返回的JSON
        import json
        result = json.loads(response.choices[0].message.content)

        await record_usage(customer_id, "intent", response.usage.total_tokens)

        return result

    except Exception as e:
        logger.error(f"意图识别失败: {e}")
        # 降级策略：返回默认意图
        return {
            "intent": "chat",
            "workflow_type": None,
            "confidence": 0.0,
            "reasoning": f"识别失败: {str(e)}"
        }
```

---

### 3. 字段提取 `/ai/fields/extract`

**用途**：从用户输入中提取表单字段值

**实现方式**：
```python
@app.post("/ai/fields/extract")
async def extract_fields(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    字段提取

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

    logger.info(f"📝 {customer_id} 请求字段提取: {len(missing_fields)}个字段")

    # 构建字段提取提示词
    system_prompt = f"""你是一个智能表单填写助手。从用户输入中提取字段值。

需要提取的字段：{', '.join(missing_fields)}

模板信息：
{json.dumps(template_data, ensure_ascii=False, indent=2)}

请从用户输入中提取这些字段的值，返回JSON格式。
如果某个字段无法从用户输入中提取，则不包含该字段。

示例：
用户输入："我要报销3000元，用于购买办公用品"
需要字段：["amount", "expense_type", "reason"]
返回：
{{
    "amount": 3000,
    "expense_type": "办公用品",
    "reason": "购买办公用品"
}}
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

        # 解析LLM返回的JSON
        import json
        extracted_fields = json.loads(response.choices[0].message.content)

        await record_usage(customer_id, "fields_extract", response.usage.total_tokens)

        return extracted_fields

    except Exception as e:
        logger.error(f"字段提取失败: {e}")
        return {}
```

---

### 4. 模板匹配 `/ai/workflow/match`

**用途**：匹配最合适的工作流模板并提取变量

**实现方式**：
```python
@app.post("/ai/workflow/match")
async def match_workflow_template(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    工作流模板匹配

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

    logger.info(f"🔄 {customer_id} 请求模板匹配: {workflow_type}")

    if not templates:
        raise HTTPException(400, "No templates provided")

    # 构建模板匹配提示词
    templates_str = json.dumps(templates, ensure_ascii=False, indent=2)
    system_prompt = f"""你是一个工作流模板匹配专家。根据用户描述，从候选模板中选择最匹配的一个。

可用模板：
{templates_str}

分析步骤：
1. 理解用户的需求描述
2. 对比每个模板的适用场景
3. 选择最匹配的模板
4. 尝试从用户描述中提取模板所需的变量值

返回JSON格式：
{{
    "matched_template_id": "模板ID",
    "confidence": 0.0-1.0,
    "extracted_variables": {{"变量名": "值"}},
    "reasoning": "匹配理由"
}}
"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户描述：{description}"}
            ],
            temperature=0.3
        )

        # 解析LLM返回的JSON
        import json
        match_result = json.loads(response.choices[0].message.content)

        await record_usage(customer_id, "workflow_match", response.usage.total_tokens)

        return match_result

    except Exception as e:
        logger.error(f"模板匹配失败: {e}")
        # 降级策略：返回第一个模板
        if templates:
            return {
                "matched_template_id": templates[0]["id"],
                "confidence": 0.5,
                "extracted_variables": {},
                "reasoning": f"匹配失败，返回默认模板: {str(e)}"
            }
        raise HTTPException(500, f"模板匹配失败: {str(e)}")
```

---

## 📋 部署步骤

### 1. 更新core_server.py

将以上4个缺失的API端点添加到 `ai-oa-core/core_server.py` 中。

### 2. 添加必要的导入

在文件顶部添加：
```python
import json
from fastapi.responses import StreamingResponse
```

### 3. 重启服务

```bash
# SSH到阿里云服务器
ssh root@<your-aliyun-ip>

# 重启核心服务
supervisorctl restart ai-oa-core

# 查看日志
tail -f /var/log/ai-oa-core/app.log
```

---

## 🧪 测试API

### 测试流式聊天
```bash
curl -X POST https://47.115.206.147/ai/chat/stream \
  -H "Authorization: Bearer test_key_001" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "你好，请介绍一下自己"}
    ],
    "model": "glm-4"
  }'
```

### 测试意图识别
```bash
curl -X POST https://47.115.206.147/ai/intent \
  -H "Authorization: Bearer test_key_001" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "我要报销3000元差旅费"
  }'
```

### 测试字段提取
```bash
curl -X POST https://47.115.206.147/ai/fields/extract \
  -H "Authorization: Bearer test_key_001" \
  -H "Content-Type: application/json" \
  -d '{
    "user_response": "我要报销3000元，用于购买办公用品",
    "missing_fields": ["amount", "expense_type", "reason"],
    "template_data": {}
  }'
```

### 测试模板匹配
```bash
curl -X POST https://47.115.206.147/ai/workflow/match \
  -H "Authorization: Bearer test_key_001" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "我要报销3000元差旅费",
    "workflow_type": "报销",
    "templates": [
      {
        "id": "tpl_001",
        "name": "报销申请",
        "description": "用于报销费用"
      },
      {
        "id": "tpl_002",
        "name": "差旅报销",
        "description": "差旅费用报销"
      }
    ]
  }'
```

---

## ✅ 完成检查清单

- [ ] 添加 `/ai/chat/stream` 端点
- [ ] 添加 `/ai/intent` 端点
- [ ] 添加 `/ai/fields/extract` 端点
- [ ] 添加 `/ai/workflow/match` 端点
- [ ] 完善 `/ai/workflow/generate` 实现（目前是TODO）
- [ ] 测试所有新增API
- [ ] 更新API文档

---

## 📝 后续优化建议

1. **迁移Agent代码** - 将7个Agent从客户端迁移到核心服务器
2. **提示词管理** - 补充完整的提示词文件（目前只有3个）
3. **错误处理** - 增强异常处理和降级策略
4. **缓存机制** - 对高频请求（如意图识别）增加缓存
5. **监控告警** - 添加性能监控和异常告警
