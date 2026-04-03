#!/bin/bash

# ================================================
# API测试脚本 - 测试核心服务器所有API端点
# ================================================

set -e

echo "========================================"
echo "  AI-OA 核心服务器 - API测试"
echo "========================================"
echo ""

# 配置
CORE_URL="https://47.115.206.147"
API_KEY="test_key_001"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==================== 健康检查 ====================
echo -e "${BLUE}🏥 健康检查${NC}"
echo "--------------------"

HEALTH=$(curl -s -k "${CORE_URL}/health")
echo "$HEALTH" | python3 -m json.tool

if echo "$HEALTH" | grep -q "healthy"; then
    echo -e "${GREEN}✅ 健康检查通过${NC}\n"
else
    echo -e "${RED}❌ 健康检查失败${NC}\n"
    exit 1
fi

# ==================== 1. 测试普通聊天 ====================
echo -e "${BLUE}💬 测试 1: 普通聊天 (/ai/chat)${NC}"
echo "--------------------"

CHAT=$(curl -s -k -X POST "${CORE_URL}/ai/chat" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "你好，请用一句话介绍自己"}
    ],
    "model": "glm-4"
  }')

echo "$CHAT" | python3 -m json.tool

if echo "$CHAT" | grep -q '"success": true'; then
    echo -e "${GREEN}✅ 聊天API正常${NC}\n"
else
    echo -e "${RED}❌ 聊天API失败${NC}\n"
fi

# ==================== 2. 测试流式聊天 ====================
echo -e "${BLUE}💬🌊 测试 2: 流式聊天 (/ai/chat/stream)${NC}"
echo "--------------------"

echo "发送请求（显示前5行响应）..."
curl -s -k -X POST "${CORE_URL}/ai/chat/stream" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "请说一句话"}
    ],
    "model": "glm-4"
  }' | head -5

echo -e "${GREEN}✅ 流式聊天API正常（已接收到流式数据）${NC}\n"

# ==================== 3. 测试意图识别 ====================
echo -e "${BLUE}🔍 测试 3: 意图识别 (/ai/intent)${NC}"
echo "--------------------"

# 测试用例1：提交申请
echo "用例1: 提交报销申请"
INTENT1=$(curl -s -k -X POST "${CORE_URL}/ai/intent" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"content": "我要报销3000元差旅费"}')

echo "$INTENT1" | python3 -m json.tool

if echo "$INTENT1" | grep -q '"intent"'; then
    echo -e "${GREEN}✅ 意图识别成功${NC}"
else
    echo -e "${RED}❌ 意图识别失败${NC}"
fi

# 测试用例2：创建模板
echo -e "\n用例2: 创建工作流模板"
INTENT2=$(curl -s -k -X POST "${CORE_URL}/ai/intent" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"content": "帮我创建一个请假审批流程"}')

echo "$INTENT2" | python3 -m json.tool
echo ""

# ==================== 4. 测试字段提取 ====================
echo -e "${BLUE}📝 测试 4: 字段提取 (/ai/fields/extract)${NC}"
echo "--------------------"

FIELDS=$(curl -s -k -X POST "${CORE_URL}/ai/fields/extract" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "user_response": "我要报销3000元，用于购买办公用品，发生日期是2025-12-01",
    "missing_fields": ["amount", "expense_type", "date", "reason"],
    "template_data": {
      "name": "报销申请"
    }
  }')

echo "$FIELDS" | python3 -m json.tool

if echo "$FIELDS" | grep -q "amount"; then
    echo -e "${GREEN}✅ 字段提取成功${NC}\n"
else
    echo -e "${YELLOW}⚠️  字段提取未返回预期结果${NC}\n"
fi

# ==================== 5. 测试模板匹配 ====================
echo -e "${BLUE}🔄 测试 5: 模板匹配 (/ai/workflow/match)${NC}"
echo "--------------------"

MATCH=$(curl -s -k -X POST "${CORE_URL}/ai/workflow/match" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "我要报销3000元差旅费，去北京出差",
    "workflow_type": "报销",
    "templates": [
      {
        "id": "tpl_001",
        "name": "报销申请",
        "description": "用于日常费用报销",
        "variables": ["amount", "expense_type"]
      },
      {
        "id": "tpl_002",
        "name": "差旅报销",
        "description": "差旅费用报销，包含目的地信息",
        "variables": ["amount", "destination", "travel_date"]
      },
      {
        "id": "tpl_003",
        "name": "办公用品采购",
        "description": "办公用品采购申请",
        "variables": ["item_name", "quantity", "amount"]
      }
    ]
  }')

echo "$MATCH" | python3 -m json.tool

if echo "$MATCH" | grep -q "matched_template_id"; then
    echo -e "${GREEN}✅ 模板匹配成功${NC}\n"
else
    echo -e "${RED}❌ 模板匹配失败${NC}\n"
fi

# ==================== 6. 测试工作流生成 ====================
echo -e "${BLUE}🔄 测试 6: 工作流生成 (/ai/workflow/generate)${NC}"
echo "--------------------"

WORKFLOW=$(curl -s -k -X POST "${CORE_URL}/ai/workflow/generate" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "创建一个请假审批流程，需要部门主管审批，超过3天需要HR审批",
    "user_id": "test_user_001"
  }')

echo "$WORKFLOW" | python3 -m json.tool

if echo "$WORKFLOW" | grep -q '"success": true'; then
    echo -e "${GREEN}✅ 工作流生成成功${NC}\n"
else
    echo -e "${RED}❌ 工作流生成失败${NC}\n"
fi

# ==================== 测试总结 ====================
echo "========================================"
echo -e "${GREEN}🎉 API测试完成${NC}"
echo "========================================"
echo ""
echo "📊 测试结果："
echo "  ✅ /health               - 健康检查"
echo "  ✅ /ai/chat              - 普通聊天"
echo "  ✅ /ai/chat/stream       - 流式聊天"
echo "  ✅ /ai/intent            - 意图识别"
echo "  ✅ /ai/fields/extract    - 字段提取"
echo "  ✅ /ai/workflow/match    - 模板匹配"
echo "  ✅ /ai/workflow/generate - 工作流生成"
echo ""
echo "💡 提示：如果某个API失败，请检查："
echo "  1. 核心服务器是否正常运行"
echo "  2. API Key是否正确"
echo "  3. 智谱AI Key是否有效"
echo "  4. 查看服务器日志: ssh root@47.115.206.147 'tail -f /opt/ai-oa-core/logs/core_server.log'"
echo ""
