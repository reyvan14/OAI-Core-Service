#!/bin/bash

# ================================================
# 核心服务器API补充脚本
# 用途：将缺失的API端点部署到阿里云核心服务器
# ================================================

set -e

echo "========================================"
echo "  AI-OA 核心服务器 - API补充部署"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
ALIYUN_IP="47.115.206.147"
ALIYUN_USER="root"
CORE_DIR="/opt/ai-oa-core"

# ==================== 1. 检查本地文件 ====================
echo -e "${BLUE}📋 步骤1: 检查本地补充文件...${NC}"

if [ ! -f "ai-oa-core/core_server_补充API.py" ]; then
    echo -e "${RED}❌ 找不到补充API文件${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 补充API文件存在${NC}"
echo ""

# ==================== 2. 备份服务器代码 ====================
echo -e "${BLUE}💾 步骤2: 备份服务器原有代码...${NC}"

ssh ${ALIYUN_USER}@${ALIYUN_IP} << 'EOF'
    cd /opt/ai-oa-core

    # 创建备份目录
    BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p $BACKUP_DIR

    # 备份core_server.py
    if [ -f "core_server.py" ]; then
        cp core_server.py $BACKUP_DIR/
        echo "✅ 已备份 core_server.py 到 $BACKUP_DIR"
    fi

    echo "备份完成！"
EOF

echo ""

# ==================== 3. 上传补充代码 ====================
echo -e "${BLUE}📤 步骤3: 上传补充API代码...${NC}"

scp ai-oa-core/core_server_补充API.py ${ALIYUN_USER}@${ALIYUN_IP}:${CORE_DIR}/

echo -e "${GREEN}✅ 补充代码已上传${NC}"
echo ""

# ==================== 4. 合并代码 ====================
echo -e "${BLUE}🔧 步骤4: 合并API端点到core_server.py...${NC}"

ssh ${ALIYUN_USER}@${ALIYUN_IP} << 'EOF'
    cd /opt/ai-oa-core

    echo "正在合并API端点..."

    # 检查core_server.py是否已包含新API
    if grep -q "ai/chat/stream" core_server.py; then
        echo "⚠️  检测到core_server.py已包含新API，跳过合并"
    else
        echo "📝 开始合并..."

        # 方法1：直接追加（简单但不优雅）
        # 找到最后一个@app装饰器的位置，在前面插入新代码

        # 备份
        cp core_server.py core_server.py.before_merge

        # 提取补充代码（去掉开头的导入和注释）
        tail -n +10 core_server_补充API.py > temp_apis.txt

        # 在core_server.py的管理API之前插入新API
        # 找到"# ==================== 管理API ===================="的行号
        LINE_NUM=$(grep -n "# ==================== 管理API ====================" core_server.py | cut -d: -f1)

        if [ -z "$LINE_NUM" ]; then
            echo "❌ 找不到插入位置，请手动合并"
            exit 1
        fi

        # 分割文件
        head -n $((LINE_NUM - 1)) core_server.py > core_server_part1.txt
        tail -n +$LINE_NUM core_server.py > core_server_part2.txt

        # 合并
        cat core_server_part1.txt temp_apis.txt core_server_part2.txt > core_server.py

        # 清理临时文件
        rm temp_apis.txt core_server_part1.txt core_server_part2.txt

        echo "✅ API合并完成"
    fi
EOF

echo ""

# ==================== 5. 更新导入 ====================
echo -e "${BLUE}📦 步骤5: 更新导入语句...${NC}"

ssh ${ALIYUN_USER}@${ALIYUN_IP} << 'EOF'
    cd /opt/ai-oa-core

    # 检查是否已有必要的导入
    if ! grep -q "from fastapi.responses import StreamingResponse" core_server.py; then
        # 在from fastapi import后面添加StreamingResponse
        sed -i '/from fastapi import/a from fastapi.responses import StreamingResponse' core_server.py
        echo "✅ 添加 StreamingResponse 导入"
    fi

    if ! grep -q "^import json" core_server.py; then
        # 在文件开头添加json导入
        sed -i '1i import json' core_server.py
        echo "✅ 添加 json 导入"
    fi

    echo "导入更新完成"
EOF

echo ""

# ==================== 6. 验证语法 ====================
echo -e "${BLUE}🔍 步骤6: 验证Python语法...${NC}"

ssh ${ALIYUN_USER}@${ALIYUN_IP} << 'EOF'
    cd /opt/ai-oa-core

    # 激活虚拟环境
    source venv/bin/activate

    # 语法检查
    python3 -m py_compile core_server.py

    if [ $? -eq 0 ]; then
        echo "✅ Python语法检查通过"
    else
        echo "❌ Python语法错误，请检查"
        exit 1
    fi
EOF

echo ""

# ==================== 7. 重启服务 ====================
echo -e "${BLUE}🔄 步骤7: 重启核心服务...${NC}"

ssh ${ALIYUN_USER}@${ALIYUN_IP} << 'EOF'
    # 重启supervisor管理的服务
    supervisorctl restart ai-oa-core

    # 等待服务启动
    sleep 3

    # 检查状态
    supervisorctl status ai-oa-core
EOF

echo ""

# ==================== 8. 健康检查 ====================
echo -e "${BLUE}🏥 步骤8: 健康检查...${NC}"

# 等待服务完全启动
sleep 2

# 测试健康检查端点
HEALTH_CHECK=$(curl -s http://${ALIYUN_IP}:9000/health)

if echo "$HEALTH_CHECK" | grep -q "healthy"; then
    echo -e "${GREEN}✅ 核心服务健康检查通过${NC}"
    echo "$HEALTH_CHECK" | python3 -m json.tool
else
    echo -e "${RED}❌ 核心服务健康检查失败${NC}"
    echo "$HEALTH_CHECK"
fi

echo ""

# ==================== 9. 测试新增API ====================
echo -e "${BLUE}🧪 步骤9: 测试新增API端点...${NC}"

API_KEY="test_key_001"

# 测试1：意图识别
echo "测试 /ai/intent ..."
INTENT_RESULT=$(curl -s -X POST "http://${ALIYUN_IP}:9000/ai/intent" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"content": "我要报销3000元"}')

if echo "$INTENT_RESULT" | grep -q "intent"; then
    echo -e "${GREEN}✅ /ai/intent 正常${NC}"
else
    echo -e "${YELLOW}⚠️  /ai/intent 返回异常: $INTENT_RESULT${NC}"
fi

# 测试2：字段提取
echo "测试 /ai/fields/extract ..."
FIELDS_RESULT=$(curl -s -X POST "http://${ALIYUN_IP}:9000/ai/fields/extract" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "user_response": "我要报销3000元，用于购买办公用品",
    "missing_fields": ["amount", "expense_type"],
    "template_data": {}
  }')

if echo "$FIELDS_RESULT" | grep -q "amount"; then
    echo -e "${GREEN}✅ /ai/fields/extract 正常${NC}"
else
    echo -e "${YELLOW}⚠️  /ai/fields/extract 返回异常${NC}"
fi

echo ""

# ==================== 完成 ====================
echo "========================================"
echo -e "${GREEN}🎉 API补充部署完成！${NC}"
echo "========================================"
echo ""
echo "📋 新增API端点："
echo "  ✅ POST /ai/chat/stream      - 流式聊天"
echo "  ✅ POST /ai/intent           - 意图识别"
echo "  ✅ POST /ai/fields/extract   - 字段提取"
echo "  ✅ POST /ai/workflow/match   - 模板匹配"
echo "  ✅ POST /ai/workflow/generate - 工作流生成（完善）"
echo ""
echo "🔧 管理命令："
echo "  查看状态: ssh ${ALIYUN_USER}@${ALIYUN_IP} 'supervisorctl status ai-oa-core'"
echo "  查看日志: ssh ${ALIYUN_USER}@${ALIYUN_IP} 'tail -f /opt/ai-oa-core/logs/core_server.log'"
echo "  重启服务: ssh ${ALIYUN_USER}@${ALIYUN_IP} 'supervisorctl restart ai-oa-core'"
echo ""
echo "🧪 测试脚本："
echo "  bash ai-oa-core/test_all_apis.sh"
echo ""
