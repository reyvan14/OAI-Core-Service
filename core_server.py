"""
AI-OA 核心服务器
提供核心AI能力的私有服务

职责：
1. 7个专业化Agent服务
2. Agent调度编排
3. 提示词管理（加密）
4. 客户授权管理
5. 配额控制和计费
6. 监控和审计
"""

import os
import logging
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
from zhipuai import ZhipuAI

# 导入核心服务和Agent
from app.agents.search_agent import SearchAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.approve_agent import ApproveAgent
from app.agents.learn_agent import LearnAgent
from app.agents.config_agent import ConfigAgent
from app.services.skill_loader import skill_loader


# 配置日志
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG级别，方便排查问题
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/core_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== 生命周期管理 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 核心服务器启动中...")

    # 启动时初始化
    await startup_event()

    yield

    # 关闭时清理
    await shutdown_event()
    logger.info("👋 核心服务器已关闭")


async def startup_event():
    """启动事件"""
    # 1. 加载配置
    logger.info("📝 加载配置...")
    app.state.config = load_config()

    # 2. 初始化数据库连接（客户授权管理）
    logger.info("💾 初始化数据库...")
    # TODO: 初始化客户授权数据库

    # 3. 加载提示词（加密）
    logger.info("🔐 加载提示词（加密）...")
    # TODO: 初始化提示词加载器

    # 4. 初始化Agent
    logger.info("🤖 初始化Agent...")
    app.state.agents = await initialize_agents()

    # 5. 初始化监控
    logger.info("📊 初始化监控系统...")
    # TODO: 初始化监控

    logger.info("✅ 核心服务器启动完成")


async def shutdown_event():
    """关闭事件"""
    logger.info("正在关闭核心服务器...")
    # TODO: 清理资源


def load_config() -> Dict:
    """加载配置"""
    return {
        "zhipu_api_key": os.getenv("ZHIPU_API_KEY"),
        "encryption_key": os.getenv("ENCRYPTION_KEY"),
        "allowed_api_keys": set(os.getenv("ALLOWED_API_KEYS", "").split(",")),
        "environment": os.getenv("ENVIRONMENT", "production"),
    }


async def initialize_agents():
    """初始化所有Agent"""
    logger.info("🤖 正在初始化Agent...")

    try:
        agents = {
            "search": SearchAgent(),
            "analytics": AnalyticsAgent(),
            "approve": ApproveAgent(),
            "learn": LearnAgent(),
            "config": ConfigAgent(),
        }

        # 预热所有Agent
        for name, agent in agents.items():
            try:
                await agent.warm_up()
                logger.info(f"✅ {name} Agent 初始化完成")
            except Exception as e:
                logger.warning(f"⚠️ {name} Agent 预热失败: {e}")

        logger.info(f"✅ 成功初始化 {len(agents)} 个Agent")
        return agents

    except Exception as e:
        logger.error(f"❌ Agent初始化失败: {e}")
        logger.info("⚠️ 继续运行（API直接调用智谱AI）")
        return {}


# ==================== FastAPI应用 ====================
app = FastAPI(
    title="AI-OA Core Service",
    description="AI-OA核心智能服务（私有）",
    version="1.0.0",
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "false") == "true" else None,
    lifespan=lifespan
)

# CORS配置（严格控制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ==================== 安全：API Key验证 ====================
async def verify_api_key(authorization: str = Header(None)) -> str:
    """
    验证API Key

    Args:
        authorization: Authorization header (Bearer <api_key>)

    Returns:
        客户ID

    Raises:
        HTTPException: 401 如果验证失败
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected: Bearer <api_key>"
        )

    api_key = authorization.replace("Bearer ", "")

    # TODO: 从数据库查询API Key
    # 临时实现：从配置读取
    if api_key not in app.state.config["allowed_api_keys"]:
        logger.warning(f"❌ 非法API Key尝试访问: {api_key[:10]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    # TODO: 返回实际的客户ID
    customer_id = f"customer_{api_key[:8]}"
    logger.info(f"✅ API Key验证通过: {customer_id}")

    return customer_id


# ==================== 配额控制 ====================
async def check_quota(customer_id: str) -> bool:
    """
    检查客户配额

    Args:
        customer_id: 客户ID

    Returns:
        是否还有配额
    """
    # TODO: 从数据库查询配额
    # 临时实现：总是返回True
    return True


async def record_usage(customer_id: str, operation: str, tokens: int):
    """
    记录使用情况

    Args:
        customer_id: 客户ID
        operation: 操作类型
        tokens: 消耗的tokens
    """
    # TODO: 记录到数据库
    logger.info(f"📊 记录使用: {customer_id} - {operation} - {tokens} tokens")


# ==================== 核心API端点 ====================
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "ai-oa-core",
        "version": "1.0.0"
    }


# ==================== Skill API端点 ====================
@app.get("/ai/skills")
async def list_skills(customer_id: str = Depends(verify_api_key)):
    """
    列出所有可用的 Skill

    Returns:
        Skill 列表
    """
    skills = skill_loader.list_skills()
    return {
        "success": True,
        "skills": skills
    }


@app.get("/ai/skills/{skill_name}")
async def get_skill(
    skill_name: str,
    customer_id: str = Depends(verify_api_key)
):
    """
    获取指定 Skill 的内容

    Args:
        skill_name: Skill 名称

    Returns:
        Skill 内容
    """
    skill = skill_loader.load(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    return {
        "success": True,
        "skill": skill.to_dict()
    }


@app.post("/ai/skills/system-prompt")
async def get_system_prompt(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    获取智能体的 system_prompt

    Body:
        agent_type: 智能体类型 (process/knowledge)
        skill_name: 指定的 Skill 名称（可选）
        extra_prompt: 额外的补充指令（可选）

    Returns:
        完整的 system_prompt
    """
    body = await request.json()
    agent_type = body.get("agent_type", "process")
    skill_name = body.get("skill_name")
    extra_prompt = body.get("extra_prompt")

    system_prompt = skill_loader.get_system_prompt(
        agent_type=agent_type,
        skill_name=skill_name,
        extra_prompt=extra_prompt
    )

    return {
        "success": True,
        "system_prompt": system_prompt
    }


@app.post("/ai/skills/clear-cache")
async def clear_skill_cache(customer_id: str = Depends(verify_api_key)):
    """
    清除 Skill 缓存（用于热更新）
    """
    skill_loader.clear_cache()
    return {
        "success": True,
        "message": "Skill cache cleared"
    }


@app.post("/ai/chat")
async def ai_chat(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """智能对话"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "glm-4.6")
    temperature = body.get("temperature", 0.7)

    logger.info(f"💬 {customer_id} 请求对话: {len(messages)}条消息")

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        llm_response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            thinking={"type": "disabled"}  # 关闭思维链，加快普通对话响应速度
        )
        
        response = {
            "success": True,
            "data": {
                "content": llm_response.choices[0].message.content,
                "model": model,
                "usage": {
                    "prompt_tokens": llm_response.usage.prompt_tokens,
                    "completion_tokens": llm_response.usage.completion_tokens,
                    "total_tokens": llm_response.usage.total_tokens
                }
            }
        }
        
        await record_usage(customer_id, "chat", llm_response.usage.total_tokens)
        return response
        
    except Exception as e:
        logger.error(f"❌ 智谱AI调用失败: {e}")
        raise HTTPException(500, f"LLM调用失败: {str(e)}")


@app.post("/ai/form/fill")
async def form_fill(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """智能表单填写"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    user_input = body.get("user_input")
    form_schema = body.get("form_schema")

    logger.info(f"📝 {customer_id} 请求表单填写")

    try:
        form_agent = app.state.agents.get("form")
        if not form_agent:
            raise Exception("FormAgent未初始化")
        
        result = await form_agent.process({
            "user_input": user_input,
            "form_schema": form_schema
        })
        
        await record_usage(customer_id, "form_fill", 200)
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error(f"❌ 表单填写失败: {e}")
        raise HTTPException(500, str(e))


@app.post("/ai/approve")
async def approve_decision(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    智能审批决策

    请求格式：
    {
        "request_data": {...},  # 审批请求数据，包含amount, type, description等
        "context": {...}        # 审批人上下文，包含user_id, user_role等
    }
    """
    import time
    start_time = time.time()

    # 1. 检查配额
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    # 2. 解析请求
    body = await request.json()
    request_data = body.get("request_data")
    context = body.get("context", {})

    if not request_data:
        raise HTTPException(400, "request_data不能为空")

    logger.info(f"[approve] customer={customer_id} request_type={request_data.get('type')} amount={request_data.get('amount')}")

    # 3. 获取ApproveAgent
    approve_agent = app.state.agents.get("approve")
    if not approve_agent:
        logger.error("ApproveAgent未初始化")
        raise HTTPException(500, "审批服务暂不可用")

    try:
        # 4. 构建审批请求列表和审批人上下文
        approval_requests = [request_data] if isinstance(request_data, dict) else request_data
        approver_context = {
            "user_id": context.get("user_id", customer_id),
            "user_role": context.get("user_role", "approver"),
            "department": context.get("department", ""),
        }

        # 5. 调用ApproveAgent进行智能审批分析
        result = await approve_agent.smart_approval(
            approval_requests=approval_requests,
            approver_context=approver_context
        )

        elapsed = time.time() - start_time

        if result.get("success"):
            # 从分析结果中提取决策
            recommendations = result.get("recommendations", [])
            first_rec = recommendations[0] if recommendations else {}

            response = {
                "success": True,
                "data": {
                    "decision": "approve" if first_rec.get("auto_approve") else "review",
                    "confidence": result.get("analyzed_requests", [{}])[0].get("compliance_score", 0.5),
                    "reason": first_rec.get("reason", "需要进一步审核"),
                    "risk_level": first_rec.get("risk_level", "中"),
                    "recommendations": recommendations,
                    "auto_approve_count": result.get("auto_approve_count", 0),
                    "manual_review_count": result.get("manual_review_count", 0),
                }
            }
            logger.info(f"[approve] SUCCESS customer={customer_id} elapsed={elapsed:.2f}s risk_level={first_rec.get('risk_level')} auto_approve={first_rec.get('auto_approve')}")
        else:
            response = {
                "success": False,
                "error": result.get("error", "审批分析失败"),
                "message": result.get("message", "请稍后重试")
            }
            logger.warning(f"[approve] FAILED customer={customer_id} elapsed={elapsed:.2f}s error={result.get('error')}")

        await record_usage(customer_id, "approve", 250)
        return response

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[approve] ERROR customer={customer_id} elapsed={elapsed:.2f}s error={str(e)}", exc_info=True)
        raise HTTPException(500, f"审批分析失败: {str(e)}")


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
    model = body.get("model", "glm-4.6")

    logger.info(f"💬🌊 {customer_id} 请求流式对话: {len(messages)}条消息")

    async def generate():
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
                    yield f"data: {content}\n\n"

            yield "data: [DONE]\n\n"
            await record_usage(customer_id, "chat_stream", len(total_content) * 2)

        except Exception as e:
            logger.error(f"流式聊天失败: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/ai/intent")
async def analyze_intent(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """意图识别"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    content = body.get("content", "")

    if not content:
        raise HTTPException(400, "content不能为空")

    logger.info(f"🔍 {customer_id} 请求意图识别: {content[:50]}...")

    system_prompt = """你是一个意图识别专家。分析用户输入，判断用户意图。

可能的意图类型：
1. submit_application - 用户想提交申请（报销、请假等）
2. create_template - 用户想创建工作流模板
3. chat - 普通对话

返回JSON格式（不要markdown代码块）：
{
    "intent": "submit_application",
    "workflow_type": "报销",
    "confidence": 0.95,
    "reasoning": "判断理由"
}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户输入：{content}"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "intent", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"意图识别失败: {e}")
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
    """字段提取"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    user_response = body.get("user_response", "")
    missing_fields = body.get("missing_fields", [])
    template_data = body.get("template_data", {})

    if not user_response or not missing_fields:
        raise HTTPException(400, "user_response和missing_fields不能为空")

    logger.info(f"📝 {customer_id} 请求字段提取: {len(missing_fields)}个字段")

    system_prompt = f"""从用户输入中提取字段值。

需要字段：{', '.join(missing_fields)}
模板：{json.dumps(template_data, ensure_ascii=False)}

返回纯JSON（不要markdown）：
{{"amount": 3000, "expense_type": "办公用品"}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_response}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(llm_output)

        await record_usage(customer_id, "fields_extract", response.usage.total_tokens)
        return extracted

    except Exception as e:
        logger.error(f"字段提取失败: {e}")
        return {}


@app.post("/ai/knowledge/search")
async def knowledge_search(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    知识库智能搜索

    请求格式：
    {
        "query": "报销流程是什么",
        "collections": ["company_policies", "procedures"],  # 可选，指定搜索的集合
        "top_k": 5  # 可选，返回结果数量
    }
    """
    import time
    start_time = time.time()

    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    query = body.get("query", "")
    collections = body.get("collections")  # None表示搜索所有集合
    top_k = body.get("top_k", 5)

    if not query:
        raise HTTPException(400, "query不能为空")

    logger.info(f"[knowledge/search] customer={customer_id} query={query[:50]}... collections={collections} top_k={top_k}")

    # 获取SearchAgent
    search_agent = app.state.agents.get("search")
    if not search_agent:
        logger.error("SearchAgent未初始化")
        raise HTTPException(500, "搜索服务暂不可用")

    try:
        # 构建用户上下文
        user_context = {
            "user_id": customer_id,
            "user_role": "user",
        }

        # 调用SearchAgent进行智能搜索
        result = await search_agent.intelligent_search(
            query=query,
            user_context=user_context,
            collections=collections,
            top_k=top_k
        )

        elapsed = time.time() - start_time

        if result.get("success"):
            response = {
                "success": True,
                "data": {
                    "query": query,
                    "answer": result.get("answer", ""),
                    "sources": result.get("sources", []),
                    "retrieved_count": result.get("retrieved_count", 0),
                    "search_analysis": result.get("search_analysis", {}),
                    "suggestions": result.get("suggestions", []),
                    "processing_time": result.get("processing_time", elapsed)
                }
            }
            logger.info(f"[knowledge/search] SUCCESS customer={customer_id} elapsed={elapsed:.2f}s retrieved_count={result.get('retrieved_count', 0)}")
        else:
            response = {
                "success": False,
                "error": result.get("error", "搜索失败"),
                "message": result.get("message", "请稍后重试")
            }
            logger.warning(f"[knowledge/search] FAILED customer={customer_id} elapsed={elapsed:.2f}s error={result.get('error')}")

        await record_usage(customer_id, "knowledge_search", 150)
        return response

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[knowledge/search] ERROR customer={customer_id} elapsed={elapsed:.2f}s error={str(e)}", exc_info=True)
        raise HTTPException(500, f"搜索失败: {str(e)}")


@app.post("/ai/workflow/match")
async def match_workflow_template(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """模板匹配"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    workflow_type = body.get("workflow_type")
    templates = body.get("templates", [])

    if not description or not templates:
        raise HTTPException(400, "description和templates不能为空")

    logger.info(f"🔄 {customer_id} 请求模板匹配: {len(templates)}个候选")

    system_prompt = f"""从候选模板中选择最匹配的。

模板：{json.dumps(templates, ensure_ascii=False)}

返回JSON（不要markdown）：
{{
    "matched_template_id": "tpl_002",
    "confidence": 0.92,
    "extracted_variables": {{"amount": 3000}},
    "reasoning": "理由"
}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": description}
            ],
            temperature=0.3,
            thinking={"type": "disabled"}  # 关闭思维链，加快响应速度（模板匹配不需要深度推理）
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "workflow_match", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"模板匹配失败: {e}")
        if templates:
            return {
                "matched_template_id": templates[0]["id"],
                "confidence": 0.5,
                "extracted_variables": {},
                "reasoning": f"匹配失败: {str(e)}"
            }
        raise HTTPException(500, str(e))


@app.post("/ai/workflow/generate")
async def workflow_generate(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """智能工作流生成"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    user_id = body.get("user_id", "")

    if not description:
        raise HTTPException(400, "description不能为空")

    logger.info(f"🔄 {customer_id} 请求工作流生成: {description[:50]}...")

    system_prompt = """你是工作流设计专家。生成完整的工作流配置JSON。

格式要求（严格按照此结构）：
{
    "name": "工作流名称",
    "description": "工作流描述",
    "category": "财务",
    "start_node_id": "start",
    "end_node_ids": ["end"],
    "nodes": [
        {
            "id": "start",
            "name": "发起申请",
            "type": "start",
            "assignee": {"type": "initiator"}
        },
        {
            "id": "node_1",
            "name": "经理审批",
            "type": "approval",
            "assignee": {"type": "role", "role": "manager"},
            "conditions": []
        },
        {
            "id": "end",
            "name": "结束",
            "type": "end"
        }
    ],
    "transitions": [
        {"from": "start", "to": "node_1"},
        {"from": "node_1", "to": "end", "condition": "approved"}
    ],
    "variables": [
        {"name": "amount", "label": "报销金额", "type": "number", "required": true},
        {"name": "reason", "label": "报销原因", "type": "text", "required": true}
    ]
}

返回纯JSON（不要markdown代码块）。"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"工作流需求：{description}"}
            ],
            temperature=0.5,
            max_tokens=2000
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        workflow_config = json.loads(llm_output)

        await record_usage(customer_id, "workflow_generate", response.usage.total_tokens)

        return {
            "success": True,
            "workflow": workflow_config,
            "model": "glm-4.6",
            "history_id": f"history_{customer_id}_{int(datetime.now().timestamp())}"
        }

    except Exception as e:
        logger.error(f"工作流生成失败: {e}")
        raise HTTPException(500, f"生成失败: {str(e)}")


@app.post("/ai/workflow/refine")
async def workflow_refine(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """工作流优化"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    workflow = body.get("workflow", {})
    feedback = body.get("feedback", "")
    user_id = body.get("user_id", "")
    history_id = body.get("history_id", "")

    if not workflow or not feedback:
        raise HTTPException(400, "workflow和feedback不能为空")

    logger.info(f"🔄 {customer_id} 请求工作流优化: {feedback[:50]}...")

    system_prompt = f"""你是工作流优化专家。根据用户反馈优化工作流配置。

当前工作流配置：
{json.dumps(workflow, ensure_ascii=False, indent=2)}

用户反馈：
{feedback}

请按照原有格式返回优化后的完整工作流配置JSON（不要markdown代码块）。"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请优化工作流"}
            ],
            temperature=0.5,
            max_tokens=2000
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        refined_workflow = json.loads(llm_output)

        await record_usage(customer_id, "workflow_refine", response.usage.total_tokens)

        return {
            "success": True,
            "workflow": refined_workflow,
            "model": "glm-4.6"
        }

    except Exception as e:
        logger.error(f"工作流优化失败: {e}")
        raise HTTPException(500, f"优化失败: {str(e)}")


@app.post("/ai/forms/fill")
async def forms_fill(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """智能表单填写"""
    import time
    start_time = time.time()

    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    message = body.get("message", "")
    form_type = body.get("form_type")

    if not message:
        raise HTTPException(400, "message不能为空")

    logger.info(f"[forms/fill] customer={customer_id} form_type={form_type} message_len={len(message)} message_preview=\"{message[:50]}...\"")

    # 定义Function Call schema
    tools = [{
        "type": "function",
        "function": {
            "name": "extract_form_fields",
            "description": "从用户描述中提取表单字段值",
            "parameters": {
                "type": "object",
                "properties": {
                    "form_type": {
                        "type": "string",
                        "description": "表单类型（请假/报销/采购等）"
                    },
                    "extracted_fields": {
                        "type": "object",
                        "description": "提取的表单字段键值对"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "提取置信度（0-1）"
                    }
                },
                "required": ["form_type", "extracted_fields", "confidence"]
            }
        }
    }]

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

        # 构建详细的提示词
        system_prompt = """你是智能表单助手，负责从用户的自然语言描述中提取结构化的表单字段。

你需要：
1. 识别表单类型（请假/报销/采购/出差/加班等）
2. 提取所有相关字段信息（日期、金额、原因、部门等）
3. 根据信息完整性计算置信度：
   - 0.9-1.0: 所有必填字段都明确提供
   - 0.7-0.9: 大部分字段提供，少量需要推断
   - 0.5-0.7: 部分字段提供，需要较多推断
   - 0.3-0.5: 信息很少，大量字段缺失
   - 0.0-0.3: 几乎没有有效信息

示例：
- "我要请假3天，从明天开始" → confidence: 0.7（有天数和开始时间，但缺少原因）
- "报销出差费用1500元，包括高铁票和住宿" → confidence: 0.85（有金额和明细，缺少日期）
"""

        user_prompt = f"""用户描述："{message}"
{f'指定表单类型：{form_type}' if form_type else ''}

请提取表单字段并评估置信度。"""

        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.3
        )

        # 提取function call结果
        message_obj = response.choices[0].message
        elapsed = time.time() - start_time

        if message_obj.tool_calls:
            result = json.loads(message_obj.tool_calls[0].function.arguments)
            await record_usage(customer_id, "forms_fill", response.usage.total_tokens)
            logger.info(f"[forms/fill] SUCCESS customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s function_call=YES confidence={result.get('confidence', 0.0):.2f} fields_count={len(result.get('extracted_fields', {}))}")
            return result
        else:
            logger.warning(f"[forms/fill] FUNCTION_CALL_FAILED customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s - using defaults")
            return {"form_type": form_type or "未知", "extracted_fields": {}, "confidence": 0.0}

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[forms/fill] ERROR customer={customer_id} elapsed={elapsed:.2f}s message_len={len(message)} error={str(e)}", exc_info=True)
        return {"form_type": form_type or "未知", "extracted_fields": {}, "confidence": 0.0}


@app.post("/ai/forms/validate")
async def forms_validate(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """表单验证"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    form_data = body.get("form_data", {})
    form_type = body.get("form_type", "")

    if not form_data:
        raise HTTPException(400, "form_data不能为空")

    logger.info(f"✅ {customer_id} 请求表单验证: {form_type}")

    system_prompt = f"""你是表单验证专家。检查表单数据的完整性和合理性。

表单类型：{form_type}
表单数据：{json.dumps(form_data, ensure_ascii=False)}

返回JSON格式（不要markdown）：
{{
    "is_valid": true,
    "errors": [],
    "warnings": ["金额较大，建议提供详细说明"]
}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请验证表单"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "forms_validate", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"表单验证失败: {e}")
        return {"is_valid": True, "errors": [], "warnings": []}


@app.post("/ai/forms/compliance")
async def forms_compliance(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """表单合规检查"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    form_data = body.get("form_data", {})
    business_rules = body.get("business_rules", [])

    if not form_data:
        raise HTTPException(400, "form_data不能为空")

    logger.info(f"⚖️ {customer_id} 请求合规检查")

    system_prompt = f"""你是合规检查专家。检查表单是否符合业务规则。

业务规则：{json.dumps(business_rules, ensure_ascii=False)}
表单数据：{json.dumps(form_data, ensure_ascii=False)}

返回JSON格式（不要markdown）：
{{
    "is_compliant": true,
    "violations": [],
    "suggestions": []
}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请检查合规性"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "forms_compliance", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"合规检查失败: {e}")
        return {"is_compliant": True, "violations": [], "suggestions": []}


@app.post("/ai/approvals/submit")
async def approvals_submit(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """审批提交分析"""
    import time
    start_time = time.time()

    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    approval_data = body.get("approval_data", {})

    if not approval_data:
        raise HTTPException(400, "approval_data不能为空")

    request_type = approval_data.get("request_type", "unknown")
    amount = approval_data.get("amount", 0)
    logger.info(f"[approvals/submit] customer={customer_id} request_type={request_type} amount={amount} fields_count={len(approval_data)}")

    # 定义Function Call schema
    tools = [{
        "type": "function",
        "function": {
            "name": "analyze_approval",
            "description": "分析审批请求并返回建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "suggested_approvers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "建议的审批人列表"
                    },
                    "estimated_duration": {
                        "type": "string",
                        "description": "预计审批时长"
                    },
                    "risk_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "风险等级"
                    },
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "审批建议"
                    }
                },
                "required": ["suggested_approvers", "estimated_duration", "risk_level"]
            }
        }
    }]

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

        # 构建详细的提示词
        system_prompt = """你是审批流程专家，负责分析审批请求并提供智能建议。

分析维度：
1. 【审批人建议】根据请求类型和金额推荐合适的审批人：
   - 请假类：直属主管 → 部门经理 → HR
   - 报销类（<5000元）：直属主管 → 财务
   - 报销类（≥5000元）：直属主管 → 部门经理 → 财务 → 总经理
   - 采购类：部门经理 → 采购部 → 财务

2. 【审批时长预估】根据流程复杂度：
   - 简单请假/报销：1-2个工作日
   - 中等金额采购（<1万）：3-5个工作日
   - 大额采购（≥1万）：5-10个工作日
   - 特殊情况：需额外说明

3. 【风险评级】
   - low: 常规请求，金额小，流程清晰
   - medium: 金额适中，需要多级审批
   - high: 大额支出、特殊请求、信息不完整

4. 【优化建议】提供改进审批效率的建议
"""

        user_prompt = f"""审批请求详情：
{json.dumps(approval_data, ensure_ascii=False, indent=2)}

请分析该审批请求，提供审批人建议、时长预估、风险评级和优化建议。"""

        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.3
        )

        # 提取function call结果
        message = response.choices[0].message
        elapsed = time.time() - start_time

        if message.tool_calls:
            result = json.loads(message.tool_calls[0].function.arguments)
            await record_usage(customer_id, "approvals_submit", response.usage.total_tokens)
            logger.info(f"[approvals/submit] SUCCESS customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s function_call=YES risk_level={result.get('risk_level')} duration={result.get('estimated_duration')} approvers_count={len(result.get('suggested_approvers', []))}")
            return result
        else:
            logger.warning(f"[approvals/submit] FUNCTION_CALL_FAILED customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s - using defaults")
            return {"suggested_approvers": [], "risk_level": "medium", "estimated_duration": "未知", "suggestions": []}

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[approvals/submit] ERROR customer={customer_id} elapsed={elapsed:.2f}s request_type={request_type} amount={amount} error={str(e)}", exc_info=True)
        return {"suggested_approvers": [], "risk_level": "medium", "estimated_duration": "未知", "suggestions": []}


@app.post("/ai/approvals/analyze")
async def approvals_analyze(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """审批智能分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    approval_id = body.get("approval_id", "")
    context = body.get("context", {})

    logger.info(f"🔍 {customer_id} 请求审批智能分析: {approval_id}")

    system_prompt = f"""你是审批决策专家。分析审批内容并给出建议。

审批上下文：{json.dumps(context, ensure_ascii=False)}

返回JSON格式（不要markdown）：
{{
    "decision_suggestion": "approve",
    "confidence": 0.85,
    "reasoning": "符合审批政策",
    "concerns": []
}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请分析审批决策"}
            ],
            temperature=0.3
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "approvals_analyze", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"审批分析失败: {e}")
        return {"decision_suggestion": "review", "confidence": 0.5}


@app.post("/ai/analytics/pain-points")
async def analytics_pain_points(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """痛点分析"""
    import time
    start_time = time.time()

    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    feedback_data = body.get("feedback_data", [])
    time_range = body.get("time_range", "30天")

    logger.info(f"[analytics/pain-points] customer={customer_id} feedback_count={len(feedback_data)} time_range={time_range}")

    # 定义Function Call schema
    tools = [{
        "type": "function",
        "function": {
            "name": "analyze_pain_points",
            "description": "分析用户反馈数据，识别主要痛点",
            "parameters": {
                "type": "object",
                "properties": {
                    "pain_points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string", "description": "痛点类别"},
                                "severity": {"type": "string", "enum": ["low", "medium", "high"], "description": "严重程度"},
                                "frequency": {"type": "integer", "description": "出现频率"},
                                "description": {"type": "string", "description": "痛点描述"}
                            }
                        },
                        "description": "识别的痛点列表"
                    },
                    "top_issues": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "最主要的问题"
                    },
                    "improvement_suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "改进建议"
                    }
                },
                "required": ["pain_points", "top_issues"]
            }
        }
    }]

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

        # 构建详细的提示词
        system_prompt = """你是数据分析专家，负责从用户反馈中识别系统痛点并提供改进建议。

分析方法：
1. 【痛点分类】将问题归类到以下类别：
   - 流程效率：审批慢、操作繁琐、步骤冗余
   - 用户体验：界面复杂、功能难找、学习成本高
   - 系统性能：加载慢、响应延迟、频繁出错
   - 功能缺失：需要但没有的功能
   - 其他：无法归类的问题

2. 【严重程度评估】
   - high: 严重影响工作效率，用户强烈不满，出现频率高（≥30次）
   - medium: 有一定影响，用户经常提及，出现频率中等（10-29次）
   - low: 影响较小，偶尔被提及，出现频率低（<10次）

3. 【频率统计】统计相同或相似问题的出现次数

4. 【改进建议】针对top 3痛点提供具体可行的改进方案
"""

        # 统计反馈数据
        total_feedback = len(feedback_data)
        feedback_summary = json.dumps(feedback_data[:20], ensure_ascii=False, indent=2)  # 取前20条

        user_prompt = f"""时间范围：{time_range}
反馈总数：{total_feedback}条

反馈数据样本：
{feedback_summary}

请识别主要痛点，评估严重程度，统计频率，并提供改进建议。"""

        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=2000
        )

        # 提取function call结果
        message = response.choices[0].message
        elapsed = time.time() - start_time

        if message.tool_calls:
            result = json.loads(message.tool_calls[0].function.arguments)
            await record_usage(customer_id, "analytics_pain_points", response.usage.total_tokens)
            pain_points_count = len(result.get("pain_points", []))
            logger.info(f"[analytics/pain-points] SUCCESS customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s function_call=YES pain_points_count={pain_points_count}")
            return {"pain_points": result.get("pain_points", []), "top_issues": result.get("top_issues", []), "improvement_suggestions": result.get("improvement_suggestions", [])}
        else:
            logger.warning(f"[analytics/pain-points] FUNCTION_CALL_FAILED customer={customer_id} model=glm-4.6 tokens={response.usage.total_tokens} elapsed={elapsed:.2f}s - using defaults")
            return {"pain_points": [], "top_issues": [], "improvement_suggestions": []}

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[analytics/pain-points] ERROR customer={customer_id} elapsed={elapsed:.2f}s feedback_count={len(feedback_data)} error={str(e)}", exc_info=True)
        return {"pain_points": [], "top_issues": [], "improvement_suggestions": []}


@app.post("/ai/analytics/query")
async def analytics_query(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """自定义数据查询分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    query = body.get("query", "")
    data = body.get("data", [])

    if not query:
        raise HTTPException(400, "query不能为空")

    logger.info(f"📊 {customer_id} 请求自定义分析: {query[:50]}...")

    system_prompt = f"""你是数据分析专家。根据用户查询分析数据。

用户查询：{query}
数据样本：{json.dumps(data[:5], ensure_ascii=False)}（共{len(data)}条）

返回JSON格式（不要markdown）：
{{
    "insights": ["发现1", "发现2"],
    "metrics": {{"average": 100, "total": 500}},
    "visualization_type": "bar_chart",
    "summary": "总体分析"
}}"""

    try:
        client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        response = client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请分析数据"}
            ],
            temperature=0.3,
            max_tokens=1500
        )

        llm_output = response.choices[0].message.content.strip()
        llm_output = llm_output.replace("```json", "").replace("```", "").strip()
        result = json.loads(llm_output)

        await record_usage(customer_id, "analytics_query", response.usage.total_tokens)
        return result

    except Exception as e:
        logger.error(f"自定义分析失败: {e}")
        return {"insights": [], "metrics": {}, "summary": "分析失败"}


@app.post("/ai/analytics")
async def analytics_analyze(
    request: Request,
    customer_id: str = Depends(verify_api_key)
):
    """
    智能数据分析

    请求格式：
    {
        "analysis_type": "usage_statistics",  # 分析类型
        "data": [...],                         # 可选的额外数据
        "query": "分析部门绩效趋势"             # 可选的自然语言查询
    }

    支持的分析类型：
    - usage_statistics: 使用统计
    - performance_metrics: 性能指标
    - user_satisfaction: 用户满意度
    - system_health: 系统健康状态
    """
    import time
    start_time = time.time()

    # 1. 检查配额
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    # 2. 解析请求
    body = await request.json()
    analysis_type = body.get("analysis_type", "usage_statistics")
    data = body.get("data", [])
    query = body.get("query")

    logger.info(f"[analytics] customer={customer_id} analysis_type={analysis_type} has_query={bool(query)}")

    # 3. 获取AnalyticsAgent
    analytics_agent = app.state.agents.get("analytics")
    if not analytics_agent:
        logger.error("AnalyticsAgent未初始化")
        raise HTTPException(500, "分析服务暂不可用")

    try:
        # 4. 构建用户上下文
        user_context = {
            "user_id": customer_id,
            "user_role": "analyst",
            "query": query,
            "extra_data": data
        }

        # 5. 调用AnalyticsAgent进行智能分析
        result = await analytics_agent.generate_insights(
            analysis_type=analysis_type,
            user_context=user_context
        )

        elapsed = time.time() - start_time

        if result.get("success"):
            response = {
                "success": True,
                "data": {
                    "analysis_type": analysis_type,
                    "data_summary": result.get("data_summary", {}),
                    "insights": result.get("insights", []),
                    "visualizations": result.get("visualizations", []),
                    "processing_time": result.get("processing_time", elapsed),
                    "generated_at": result.get("generated_at")
                }
            }
            logger.info(f"[analytics] SUCCESS customer={customer_id} elapsed={elapsed:.2f}s insights_count={len(result.get('insights', []))}")
        else:
            response = {
                "success": False,
                "error": result.get("error", "分析失败"),
                "message": result.get("message", "请稍后重试")
            }
            logger.warning(f"[analytics] FAILED customer={customer_id} elapsed={elapsed:.2f}s error={result.get('error')}")

        await record_usage(customer_id, "analytics", 400)
        return response

    except ValueError as e:
        # 不支持的分析类型
        elapsed = time.time() - start_time
        logger.warning(f"[analytics] INVALID_TYPE customer={customer_id} elapsed={elapsed:.2f}s error={str(e)}")
        raise HTTPException(400, str(e))

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[analytics] ERROR customer={customer_id} elapsed={elapsed:.2f}s error={str(e)}", exc_info=True)
        raise HTTPException(500, f"分析失败: {str(e)}")


# ==================== 管理API ====================
@app.get("/admin/usage/{customer_id}")
async def get_usage(
    customer_id: str,
    admin_key: str = Header(None)
):
    """查询客户使用情况（管理员接口）"""
    # TODO: 验证管理员权限
    if admin_key != os.getenv("ADMIN_KEY"):
        raise HTTPException(403, "Forbidden")

    # TODO: 从数据库查询
    return {
        "customer_id": customer_id,
        "monthly_usage": 1500,
        "quota": 10000,
        "remaining": 8500
    }


@app.get("/admin/customers")
async def list_customers(admin_key: str = Header(None)):
    """列出所有客户（管理员接口）"""
    # TODO: 验证管理员权限
    if admin_key != os.getenv("ADMIN_KEY"):
        raise HTTPException(403, "Forbidden")

    # TODO: 从数据库查询
    return {
        "customers": [
            {
                "id": "customer_001",
                "name": "测试客户A",
                "plan": "pro",
                "status": "active"
            }
        ]
    }


# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"❌ 未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else None
        }
    )


# ==================== 启动服务器 ====================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 9000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"🚀 启动核心服务器: {host}:{port}")

    uvicorn.run(
        "core_server:app",
        host=host,
        port=port,
        reload=False,  # 生产环境禁用热重载
        workers=1,     # 生产环境可增加worker数量
        log_level="info"
    )
