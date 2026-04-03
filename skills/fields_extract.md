---
name: 字段提取
version: "1.0"
description: 从用户输入中提取表单字段值
model: glm-5
temperature: 0.3
---

从用户输入中提取字段值。

需要字段和模板信息会在上下文中提供。

返回纯JSON（不要markdown）：
{"amount": 3000, "expense_type": "办公用品"}
