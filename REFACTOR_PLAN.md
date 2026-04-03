# OAI-Core-Service 重构方案

> 创建日期：2026-04-03
> 定性：接口层尽量不动，业务执行层按 Skill 化重写

---

## 一、现状诊断

### core_server.py（1669 行，唯一入口）

当前混合了两类职责：
1. **网关职责**：API Key 鉴权、配额检查、用量记录、CORS、异常处理
2. **业务逻辑**：13 处内联 Prompt + 14 次直接 `ZhipuAI().chat.completions.create()` 调用

### 端点分类（已验证）

| 类型 | 端点数 | 特征 | 示例 |
|------|--------|------|------|
| 纯 LLM | 9 | Prompt → LLM → JSON 解析 | `/ai/intent`, `/ai/workflow/generate`, `/ai/forms/validate` |
| LLM + Function Call | 3 | Prompt + tools schema → LLM Function Call | `/ai/forms/fill`, `/ai/approvals/submit`, `/ai/analytics/pain-points` |
| 混合编排 | 3 | 需要数据库/RAG + LLM | `/ai/approve`, `/ai/knowledge/search`, `/ai/analytics` |
| Skill 管理 | 4 | 已走 SkillLoader | `/ai/skills`, `/ai/skills/{name}`, `/ai/skills/system-prompt`, `/ai/skills/clear-cache` |
| 基础设施 | 3 | 健康检查、管理接口 | `/health`, `/admin/usage`, `/admin/customers` |

### 已知问题

- `/ai/form/fill` 端点运行时必报 500（FormAgent 未初始化）
- `prompts/` 目录下的文件（main_system.txt 等）完全未被使用
- 配额控制 `check_quota()` 永远返回 True
- 用量记录 `record_usage()` 只打 log 不入库
- 管理 API 返回硬编码假数据
- `app/` 目录下大量文件不在 core_server.py 的 import 链中

---

## 二、重构目标

### 核心原则
- **外部端点路径不变**（客户侧 `core_ai_client.py` 无需改造）
- **Prompt 外置到 Skill 文件**（.md 格式，支持热更新）
- **LLM 调用收敛到统一执行器**（消除 14 处重复代码）

### 目标架构

```
core_server.py（瘦网关，~300行）
├── 鉴权 (verify_api_key)
├── 配额 (check_quota)
├── 路由（每个端点 ~10 行：解析参数 → 调 SkillExecutor → 返回）
└── 异常处理

SkillExecutor（通用执行引擎，新建）
├── 加载 Skill 文件（Prompt + 参数）
├── 加载 tools schema（可选，从 .json sidecar）
├── 组装 messages
├── 调 LLM（普通 / stream / function_call 三种模式）
├── JSON 清洗与解析
└── 错误回退

skills/（Skill 文件目录）
├── intent_analyze.md
├── fields_extract.md
├── workflow_generate.md
├── workflow_refine.md
├── workflow_match.md
├── form_fill.md              + form_fill.tools.json
├── form_validate.md
├── form_compliance.md
├── approval_submit.md        + approval_submit.tools.json
├── approval_analyze.md
├── analytics_pain_points.md  + analytics_pain_points.tools.json
├── analytics_query.md
├── process_assistant.md      （已有）
└── knowledge_assistant.md    （已有）

pipelines/（少量 Python，处理非纯 LLM 场景）
├── knowledge_search.py       ← RAG 检索 + Skill 提供 Prompt
├── approval_decision.py      ← 数据库查询 + Skill 提供 Prompt
└── analytics_insight.py      ← 数据聚合 + Skill 提供 Prompt
```

---

## 三、交付物与顺序

### 交付物 1：扩展 SkillLoader

当前核心服务版 SkillLoader（202 行）只有基础加载/缓存/降级。
需要扩展 frontmatter 支持：

```yaml
---
name: 表单智能填写
version: "1.0"
description: 从自然语言提取表单字段
model: glm-4.6           # 新增：指定模型
temperature: 0.3          # 新增：温度参数
max_tokens: 2000          # 新增：最大 token
tools_ref: form_fill      # 新增：引用同名 .tools.json
---
```

参考客户侧版本（427 行）的 `_build_tools_section()`、`get_all_required_tools()` 等能力。

### 交付物 2：新建 SkillExecutor

统一执行引擎，替代 core_server.py 中 14 处重复的 LLM 调用模式：

输入：skill_name + user_message + 可选上下文
输出：结构化 JSON 结果

需要处理：
- 普通调用（返回 content → JSON 解析）
- Function Call（返回 tool_calls → 提取 arguments）
- 流式调用（返回 SSE generator）
- JSON 清洗（去除 ```json 包裹）
- 解析失败时的回退策略

### 交付物 3：迁移端点到 Skill 化

**第一批（9 个纯 LLM 端点）**：
- `/ai/intent` → `skills/intent_analyze.md`
- `/ai/fields/extract` → `skills/fields_extract.md`
- `/ai/workflow/generate` → `skills/workflow_generate.md`
- `/ai/workflow/refine` → `skills/workflow_refine.md`
- `/ai/workflow/match` → `skills/workflow_match.md`
- `/ai/forms/validate` → `skills/form_validate.md`
- `/ai/forms/compliance` → `skills/form_compliance.md`
- `/ai/approvals/analyze` → `skills/approval_analyze.md`
- `/ai/analytics/query` → `skills/analytics_query.md`

**第二批（3 个 Function Call 端点）**：
- `/ai/forms/fill` → `skills/form_fill.md` + `skills/form_fill.tools.json`
- `/ai/approvals/submit` → `skills/approval_submit.md` + `skills/approval_submit.tools.json`
- `/ai/analytics/pain-points` → `skills/analytics_pain_points.md` + `skills/analytics_pain_points.tools.json`

**第三批（3 个混合编排端点）**：
- `/ai/approve` → `pipelines/approval_decision.py`（保留 Python 编排，Prompt 来源改为 Skill）
- `/ai/knowledge/search` → `pipelines/knowledge_search.py`（同上）
- `/ai/analytics` → `pipelines/analytics_insight.py`（同上）

### 交付物 4：清理

- 删除不在 import 链中的文件
- 删除 `/ai/form/fill`（已坏的旧端点，被 `/ai/forms/fill` 替代）
- 清理 `core_server_补充API.py`（已合并到 core_server.py 的历史遗留）
- 统一 `prompts/` 目录：将有价值的内容迁移到 `skills/`，删除冗余文件

---

## 四、约束与风险

### 不动的部分
- 所有外部 API 路径（客户侧 core_ai_client.py 的 11 个方法不改）
- 鉴权机制（Bearer Token）
- 响应格式（保持与现有一致）

### 风险点
- SkillLoader 扩展需要同时兼容已有的 `process_assistant.md` 和 `knowledge_assistant.md`
- Function Call 的 tools schema 维护从 Python 代码搬到 .json 文件后，需要确保 JSON 合法性
- 混合编排端点依赖 Agent 类（ApproveAgent 等），这些 Agent 又依赖数据库连接，重构时不能破坏这条链路

### TODO 债务（本次不处理，记录备查）
- 配额控制实现（当前 `check_quota()` 永远返回 True）
- 用量记录入库（当前只打 log）
- 客户管理 API（当前返回硬编码数据）
- 提示词加密（当前为 TODO 注释）
