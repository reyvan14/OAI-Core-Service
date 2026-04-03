"""
AI-OA 核心服务器
提供核心AI能力的私有服务

架构（2026-04-03 重构）：
- 网关层：鉴权、配额、路由、异常处理
- 执行层：SkillExecutor（Prompt 外置到 skills/ 目录）
- 全部端点均由 Skill 驱动，无 Agent/RAG/DB 依赖
"""

import os
import logging
import json
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

# 核心执行引擎
from app.services.skill_loader import skill_loader
from app.services.skill_executor import skill_executor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
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
    logger.info("核心服务器启动中...")
    await startup_event()
    yield
    logger.info("核心服务器已关闭")


async def startup_event():
    """启动事件"""
    app.state.config = load_config()
    logger.info(f"核心服务器启动完成 (skills={len(skill_loader.list_skills())})")


def load_config() -> Dict:
    """加载配置"""
    return {
        "allowed_api_keys": set(os.getenv("ALLOWED_API_KEYS", "").split(",")),
    }


# ==================== FastAPI 应用 ====================
app = FastAPI(
    title="AI-OA Core Service",
    description="AI-OA核心智能服务（私有）",
    version="2.0.0",
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "false") == "true" else None,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ==================== 安全：API Key 验证 ====================
async def verify_api_key(authorization: str = Header(None)) -> str:
    """验证 API Key，返回客户 ID"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")

    api_key = authorization.replace("Bearer ", "")
    if api_key not in app.state.config["allowed_api_keys"]:
        logger.warning(f"非法 API Key: {api_key[:10]}...")
        raise HTTPException(401, "Invalid API key")

    return f"customer_{api_key[:8]}"


# ==================== 配额与用量（TODO: 接入数据库）====================
async def check_quota(customer_id: str) -> bool:
    # TODO: 从数据库查询配额
    return True


async def record_usage(customer_id: str, operation: str, tokens: int = 0):
    # TODO: 记录到数据库
    logger.info(f"usage: {customer_id} {operation} {tokens}tokens")


# ==================== 基础设施端点 ====================
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "ai-oa-core",
        "version": "2.0.0",
    }


# ==================== Skill 管理端点 ====================
@app.get("/ai/skills")
async def list_skills(customer_id: str = Depends(verify_api_key)):
    return {"success": True, "skills": skill_loader.list_skills()}


@app.get("/ai/skills/{skill_name}")
async def get_skill(skill_name: str, customer_id: str = Depends(verify_api_key)):
    skill = skill_loader.load(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    return {"success": True, "skill": skill.to_dict()}


@app.post("/ai/skills/system-prompt")
async def get_system_prompt(request: Request, customer_id: str = Depends(verify_api_key)):
    body = await request.json()
    system_prompt = skill_loader.get_system_prompt(
        agent_type=body.get("agent_type", "process"),
        skill_name=body.get("skill_name"),
        extra_prompt=body.get("extra_prompt"),
    )
    return {"success": True, "system_prompt": system_prompt}


@app.post("/ai/skills/clear-cache")
async def clear_skill_cache(customer_id: str = Depends(verify_api_key)):
    skill_loader.clear_cache()
    return {"success": True, "message": "Skill cache cleared"}


# ==================== 对话端点 ====================
@app.post("/ai/chat")
async def ai_chat(request: Request, customer_id: str = Depends(verify_api_key)):
    """智能对话（通用）"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    result = await skill_executor.run(
        "process_assistant",
        messages=body.get("messages", []),
        model_override=body.get("model"),
        temperature_override=body.get("temperature"),
    )

    if not result["success"]:
        raise HTTPException(500, result.get("error", "LLM调用失败"))

    await record_usage(customer_id, "chat", result["usage"]["total_tokens"])
    return {
        "success": True,
        "data": {
            "content": result["data"].get("content", result["raw"]),
            "model": result["model"],
            "usage": result["usage"],
        }
    }


@app.post("/ai/chat/stream")
async def ai_chat_stream(request: Request, customer_id: str = Depends(verify_api_key)):
    """流式聊天"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()

    return StreamingResponse(
        skill_executor.run_stream(
            "process_assistant",
            messages=body.get("messages", []),
            model_override=body.get("model"),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ==================== 纯 LLM 端点（Skill 驱动）====================
@app.post("/ai/intent")
async def analyze_intent(request: Request, customer_id: str = Depends(verify_api_key)):
    """意图识别"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content不能为空")

    result = await skill_executor.run("intent_analyze", user_message=f"用户输入：{content}")

    await record_usage(customer_id, "intent", result.get("usage", {}).get("total_tokens", 0))

    if result["success"] and isinstance(result["data"], dict) and "intent" in result["data"]:
        return result["data"]

    # 降级：返回 chat 意图
    return {"intent": "chat", "workflow_type": None, "confidence": 0.0, "reasoning": "识别失败"}


@app.post("/ai/fields/extract")
async def extract_fields(request: Request, customer_id: str = Depends(verify_api_key)):
    """字段提取"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    user_response = body.get("user_response", "")
    missing_fields = body.get("missing_fields", [])
    template_data = body.get("template_data", {})

    if not user_response or not missing_fields:
        raise HTTPException(400, "user_response和missing_fields不能为空")

    result = await skill_executor.run(
        "fields_extract",
        user_message=user_response,
        context={
            "需要字段": ", ".join(missing_fields),
            "模板": json.dumps(template_data, ensure_ascii=False),
        },
    )

    await record_usage(customer_id, "fields_extract", result.get("usage", {}).get("total_tokens", 0))
    return result["data"] if result["success"] else {}


@app.post("/ai/workflow/generate")
async def workflow_generate(request: Request, customer_id: str = Depends(verify_api_key)):
    """智能工作流生成"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    if not description:
        raise HTTPException(400, "description不能为空")

    result = await skill_executor.run("workflow_generate", user_message=f"工作流需求：{description}")

    if not result["success"]:
        raise HTTPException(500, f"生成失败: {result.get('error')}")

    await record_usage(customer_id, "workflow_generate", result["usage"]["total_tokens"])
    return {
        "success": True,
        "workflow": result["data"],
        "model": result["model"],
        "history_id": f"history_{customer_id}_{int(datetime.now().timestamp())}",
    }


@app.post("/ai/workflow/refine")
async def workflow_refine(request: Request, customer_id: str = Depends(verify_api_key)):
    """工作流优化"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    workflow = body.get("workflow", {})
    feedback = body.get("feedback", "")

    if not workflow or not feedback:
        raise HTTPException(400, "workflow和feedback不能为空")

    result = await skill_executor.run(
        "workflow_refine",
        user_message="请优化工作流",
        context={
            "当前工作流配置": json.dumps(workflow, ensure_ascii=False, indent=2),
            "用户反馈": feedback,
        },
    )

    if not result["success"]:
        raise HTTPException(500, f"优化失败: {result.get('error')}")

    await record_usage(customer_id, "workflow_refine", result["usage"]["total_tokens"])
    return {"success": True, "workflow": result["data"], "model": result["model"]}


@app.post("/ai/workflow/match")
async def match_workflow_template(request: Request, customer_id: str = Depends(verify_api_key)):
    """模板匹配"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    description = body.get("description", "")
    templates = body.get("templates", [])

    if not description or not templates:
        raise HTTPException(400, "description和templates不能为空")

    result = await skill_executor.run(
        "workflow_match",
        user_message=description,
        context={"候选模板": json.dumps(templates, ensure_ascii=False)},
    )

    await record_usage(customer_id, "workflow_match", result.get("usage", {}).get("total_tokens", 0))

    if result["success"] and isinstance(result["data"], dict) and "matched_template_id" in result["data"]:
        return result["data"]

    # 降级：返回第一个模板
    if templates:
        return {"matched_template_id": templates[0]["id"], "confidence": 0.5, "extracted_variables": {}, "reasoning": "匹配失败，返回默认模板"}
    raise HTTPException(500, "匹配失败")


@app.post("/ai/forms/validate")
async def forms_validate(request: Request, customer_id: str = Depends(verify_api_key)):
    """表单验证"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    form_data = body.get("form_data", {})
    form_type = body.get("form_type", "")

    if not form_data:
        raise HTTPException(400, "form_data不能为空")

    result = await skill_executor.run(
        "form_validate",
        user_message="请验证表单",
        context={
            "表单类型": form_type,
            "表单数据": json.dumps(form_data, ensure_ascii=False),
        },
    )

    await record_usage(customer_id, "forms_validate", result.get("usage", {}).get("total_tokens", 0))
    return result["data"] if result["success"] else {"is_valid": True, "errors": [], "warnings": []}


@app.post("/ai/forms/compliance")
async def forms_compliance(request: Request, customer_id: str = Depends(verify_api_key)):
    """表单合规检查"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    form_data = body.get("form_data", {})
    business_rules = body.get("business_rules", [])

    if not form_data:
        raise HTTPException(400, "form_data不能为空")

    result = await skill_executor.run(
        "form_compliance",
        user_message="请检查合规性",
        context={
            "业务规则": json.dumps(business_rules, ensure_ascii=False),
            "表单数据": json.dumps(form_data, ensure_ascii=False),
        },
    )

    await record_usage(customer_id, "forms_compliance", result.get("usage", {}).get("total_tokens", 0))
    return result["data"] if result["success"] else {"is_compliant": True, "violations": [], "suggestions": []}


@app.post("/ai/approvals/analyze")
async def approvals_analyze(request: Request, customer_id: str = Depends(verify_api_key)):
    """审批智能分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    context_data = body.get("context", {})

    result = await skill_executor.run(
        "approval_analyze",
        user_message="请分析审批决策",
        context={"审批上下文": json.dumps(context_data, ensure_ascii=False)},
    )

    await record_usage(customer_id, "approvals_analyze", result.get("usage", {}).get("total_tokens", 0))
    return result["data"] if result["success"] else {"decision_suggestion": "review", "confidence": 0.5}


@app.post("/ai/analytics/query")
async def analytics_query(request: Request, customer_id: str = Depends(verify_api_key)):
    """自定义数据查询分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    query = body.get("query", "")
    data = body.get("data", [])

    if not query:
        raise HTTPException(400, "query不能为空")

    result = await skill_executor.run(
        "analytics_query",
        user_message="请分析数据",
        context={
            "用户查询": query,
            "数据样本": json.dumps(data[:5], ensure_ascii=False) + f"（共{len(data)}条）",
        },
    )

    await record_usage(customer_id, "analytics_query", result.get("usage", {}).get("total_tokens", 0))
    return result["data"] if result["success"] else {"insights": [], "metrics": {}, "summary": "分析失败"}


# ==================== Function Call 端点（Skill 驱动）====================
@app.post("/ai/forms/fill")
async def forms_fill(request: Request, customer_id: str = Depends(verify_api_key)):
    """智能表单填写"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    message = body.get("message", "")
    form_type = body.get("form_type")

    if not message:
        raise HTTPException(400, "message不能为空")

    user_prompt = f'用户描述："{message}"'
    if form_type:
        user_prompt += f"\n指定表单类型：{form_type}"
    user_prompt += "\n\n请提取表单字段并评估置信度。"

    result = await skill_executor.run("form_fill", user_message=user_prompt)

    await record_usage(customer_id, "forms_fill", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        return result["data"]
    return {"form_type": form_type or "未知", "extracted_fields": {}, "confidence": 0.0}


@app.post("/ai/approvals/submit")
async def approvals_submit(request: Request, customer_id: str = Depends(verify_api_key)):
    """审批提交分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    approval_data = body.get("approval_data", {})

    if not approval_data:
        raise HTTPException(400, "approval_data不能为空")

    user_prompt = f"审批请求详情：\n{json.dumps(approval_data, ensure_ascii=False, indent=2)}\n\n请分析该审批请求，提供审批人建议、时长预估、风险评级和优化建议。"

    result = await skill_executor.run("approval_submit", user_message=user_prompt)

    await record_usage(customer_id, "approvals_submit", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        return result["data"]
    return {"suggested_approvers": [], "risk_level": "medium", "estimated_duration": "未知", "suggestions": []}


@app.post("/ai/analytics/pain-points")
async def analytics_pain_points(request: Request, customer_id: str = Depends(verify_api_key)):
    """痛点分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    feedback_data = body.get("feedback_data", [])
    time_range = body.get("time_range", "30天")

    feedback_summary = json.dumps(feedback_data[:20], ensure_ascii=False, indent=2)
    user_prompt = f"时间范围：{time_range}\n反馈总数：{len(feedback_data)}条\n\n反馈数据样本：\n{feedback_summary}\n\n请识别主要痛点，评估严重程度，统计频率，并提供改进建议。"

    result = await skill_executor.run("analytics_pain_points", user_message=user_prompt)

    await record_usage(customer_id, "analytics_pain_points", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        data = result["data"]
        return {
            "pain_points": data.get("pain_points", []),
            "top_issues": data.get("top_issues", []),
            "improvement_suggestions": data.get("improvement_suggestions", []),
        }
    return {"pain_points": [], "top_issues": [], "improvement_suggestions": []}


# ==================== 原混合编排端点（已改为 Skill 驱动）====================
@app.post("/ai/approve")
async def approve_decision(request: Request, customer_id: str = Depends(verify_api_key)):
    """智能审批决策"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    request_data = body.get("request_data")
    context = body.get("context", {})

    if not request_data:
        raise HTTPException(400, "request_data不能为空")

    user_prompt = f"审批请求：\n{json.dumps(request_data, ensure_ascii=False, indent=2)}\n\n审批人：{context.get('user_role', 'approver')}，部门：{context.get('department', '未知')}"

    result = await skill_executor.run("approval_decision", user_message=user_prompt)

    await record_usage(customer_id, "approve", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "data": {
                "decision": data.get("decision", "review"),
                "confidence": data.get("confidence", 0.5),
                "reason": data.get("reason", "需要进一步审核"),
                "risk_level": data.get("risk_level", "中"),
                "recommendations": [data],
                "auto_approve_count": 1 if data.get("auto_approve") else 0,
                "manual_review_count": 0 if data.get("auto_approve") else 1,
            }
        }
    return {"success": False, "error": "审批分析失败"}


@app.post("/ai/knowledge/search")
async def knowledge_search(request: Request, customer_id: str = Depends(verify_api_key)):
    """知识库搜索"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    query = body.get("query", "")

    if not query:
        raise HTTPException(400, "query不能为空")

    result = await skill_executor.run("knowledge_search", user_message=query)

    await record_usage(customer_id, "knowledge_search", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        data = result["data"]
        return {
            "success": True,
            "data": {
                "query": query,
                "answer": data.get("answer", data.get("content", result["raw"])),
                "sources": data.get("sources", []),
                "retrieved_count": 0,
                "suggestions": data.get("suggestions", []),
            }
        }
    return {"success": False, "error": "搜索失败"}


@app.post("/ai/analytics")
async def analytics_analyze(request: Request, customer_id: str = Depends(verify_api_key)):
    """智能数据分析"""
    if not await check_quota(customer_id):
        raise HTTPException(429, "Quota exceeded")

    body = await request.json()
    analysis_type = body.get("analysis_type", "usage_statistics")
    data = body.get("data", [])
    query = body.get("query")

    user_prompt = f"分析类型：{analysis_type}"
    if query:
        user_prompt += f"\n查询：{query}"
    if data:
        user_prompt += f"\n数据样本：{json.dumps(data[:10], ensure_ascii=False)}"

    result = await skill_executor.run("analytics_insight", user_message=user_prompt)

    await record_usage(customer_id, "analytics", result.get("usage", {}).get("total_tokens", 0))

    if result["success"]:
        return {
            "success": True,
            "data": {
                "analysis_type": analysis_type,
                "data_summary": result["data"].get("data_summary", {}),
                "insights": result["data"].get("insights", []),
                "visualizations": result["data"].get("visualizations", []),
                "generated_at": result["data"].get("generated_at"),
            }
        }
    return {"success": False, "error": "分析失败"}


# ==================== 管理 API（TODO: 接入数据库）====================
@app.get("/admin/usage/{customer_id}")
async def get_usage(customer_id: str, admin_key: str = Header(None)):
    if admin_key != os.getenv("ADMIN_KEY"):
        raise HTTPException(403, "Forbidden")
    # TODO: 从数据库查询
    return {"customer_id": customer_id, "monthly_usage": 0, "quota": 10000, "remaining": 10000}


@app.get("/admin/customers")
async def list_customers(admin_key: str = Header(None)):
    if admin_key != os.getenv("ADMIN_KEY"):
        raise HTTPException(403, "Forbidden")
    # TODO: 从数据库查询
    return {"customers": []}


# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


# ==================== 启动 ====================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 9000))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(f"启动核心服务器: {host}:{port}")
    uvicorn.run("core_server:app", host=host, port=port, reload=False, workers=1, log_level="info")
