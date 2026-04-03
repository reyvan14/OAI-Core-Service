---
name: 模板匹配
version: "1.0"
description: 从候选模板中选择最匹配用户需求的模板
model: glm-5
temperature: 0.3
---

从候选模板中选择最匹配的。

候选模板列表会在上下文中提供。

返回JSON（不要markdown）：
{
    "matched_template_id": "tpl_002",
    "confidence": 0.92,
    "extracted_variables": {"amount": 3000},
    "reasoning": "理由"
}
