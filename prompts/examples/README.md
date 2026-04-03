# 提示词编写指南

## 目录结构

```
prompts/
├── system/              # 系统级提示词
│   └── main_system.txt  # 主系统提示词
├── agents/              # 各个Agent的提示词
│   ├── workflow_generation.txt
│   ├── workflow_refinement.txt
│   ├── form_agent.txt
│   ├── search_agent.txt
│   ├── approve_agent.txt
│   ├── analytics_agent.txt
│   ├── config_agent.txt
│   └── learn_agent.txt
└── examples/            # 示例和文档
    └── README.md        # 本文件
```

## 提示词命名规范

### 系统提示词
- 文件位置: `prompts/system/`
- 访问键名: `system.{文件名}`
- 示例: `system.main` → `system/main_system.txt`

### Agent提示词
- 文件位置: `prompts/agents/`
- 访问键名: `agent.{文件名}`
- 示例: `agent.workflow_generation` → `agents/workflow_generation.txt`

## 提示词编写最佳实践

### 1. 明确角色定位
```
你是一个{具体角色}，专门负责{核心职责}。
```

### 2. 清晰的职责说明
```
你的职责：
1. {职责1}
2. {职责2}
3. {职责3}
```

### 3. 输出格式要求
```
输出要求：
- 必须返回{格式}格式
- 不要包含{不需要的内容}
- 确保{关键要求}
```

### 4. 示例和模板
```
示例输出：
{
  "field1": "value1",
  "field2": "value2"
}
```

## Agent提示词模板

### 工作流生成类Agent
适用于：根据用户需求生成结构化配置的Agent

```
你是{角色}。根据用户需求生成{输出物}。

你的职责：
1. 理解用户的{需求类型}
2. 设计合理的{核心要素}
3. 生成符合系统要求的{输出格式}
4. 确保{质量要求}

输出要求：
- 必须返回有效的{格式}格式
- 不要包含任何解释性文字
- {特殊要求}

示例{输出物}：
{JSON示例}
```

### 数据处理类Agent
适用于：分析、转换、提取数据的Agent

```
你是{角色}，专门处理{数据类型}。

你的职责：
1. 从{输入}中提取{目标信息}
2. 进行{处理步骤}
3. 返回{输出格式}

处理原则：
- {原则1}
- {原则2}

输出格式：
{格式说明或示例}
```

### 对话交互类Agent
适用于：与用户对话、提供建议的Agent

```
你是{角色}，帮助用户{目标}。

对话风格：
- {风格1，如"友好亲和"}
- {风格2，如"专业高效"}
- {风格3，如"简洁明了"}

回复原则：
1. {原则1}
2. {原则2}
3. {原则3}

不要：
- {禁止行为1}
- {禁止行为2}
```

## 提示词调试技巧

### 1. 本地测试
```bash
# 查看已加载的提示词
python -c "from app.utils.prompt_loader import prompt_loader; print(prompt_loader.list_prompts())"

# 获取特定提示词内容
python -c "from app.utils.prompt_loader import get_prompt; print(get_prompt('agent.workflow_generation'))"
```

### 2. 热重载
修改提示词文件后，重启服务或调用：
```python
from app.utils.prompt_loader import reload_prompts
reload_prompts()
```

### 3. 日志查看
提示词加载过程会输出详细日志：
```
📁 提示词加载器初始化，目录: /app/prompts
  ✓ 加载: system.main (1234 bytes)
  ✓ 加载: agent.workflow_generation (567 bytes)
✅ 提示词加载完成，共加载 8 个提示词
```

## 安全注意事项

### 1. 文件权限
```bash
# 提示词文件应设置为只读
chmod 400 prompts/agents/*.txt
chmod 400 prompts/system/*.txt
```

### 2. 敏感信息
- ❌ 不要在提示词中包含API密钥、密码等敏感信息
- ❌ 不要在提示词中硬编码用户数据
- ✅ 使用环境变量或配置文件存储敏感信息

### 3. 版本控制
- 私有提示词应存储在独立的私有Git仓库
- 使用`.gitignore`排除敏感提示词文件

## 常见问题

### Q: 提示词文件不存在会怎样？
A: 系统会使用硬编码的默认提示词（开发模式），并输出警告日志。

### Q: 如何知道Agent使用了哪个提示词？
A: 查看Agent代码中的 `prompt_loader.get()` 调用，第一个参数就是提示词键名。

### Q: 可以动态修改提示词吗？
A: 可以修改文件后调用 `reload_prompts()`，但不建议在生产环境频繁修改。

### Q: 提示词支持多语言吗？
A: 当前版本只支持单一语言。如需多语言，可通过键名区分，如 `agent.workflow_generation.en`。

## 进阶技巧

### 1. 使用变量占位符
提示词中可以包含占位符，在代码中动态替换：

```python
# prompts/agents/example.txt
你需要处理{task_type}任务，目标是{goal}。

# 代码中使用
template = get_prompt("agent.example")
prompt = template.format(task_type="数据分析", goal="生成报表")
```

### 2. 提示词分段组合
对于复杂Agent，可以将提示词拆分为多个部分：

```
prompts/agents/
├── complex_agent_role.txt
├── complex_agent_rules.txt
└── complex_agent_examples.txt
```

```python
# 代码中组合
role = get_prompt("agent.complex_agent_role")
rules = get_prompt("agent.complex_agent_rules")
examples = get_prompt("agent.complex_agent_examples")
full_prompt = f"{role}\n\n{rules}\n\n{examples}"
```

### 3. Few-shot示例
在提示词中包含高质量示例，提升AI理解能力：

```
示例1：
用户输入：{示例输入1}
正确输出：{示例输出1}

示例2：
用户输入：{示例输入2}
正确输出：{示例输出2}

现在处理真实任务：
用户输入：{实际输入}
```

## 参考资源

- OpenAI Prompt Engineering Guide: https://platform.openai.com/docs/guides/prompt-engineering
- Anthropic Prompt Guide: https://docs.anthropic.com/claude/docs/prompt-engineering
- 项目文档: `/docs/LLM_PROVIDER_MANAGEMENT.md`
