---
name: clear-memory
description: 用模板重置 workspace 中的所有 .md 文件
user-invocable: true
---

# Clear Memory Skill

用户通过 `/clear-memory` 用模板重置 workspace 中的 .md 文件。

## 用法

```
/clear-memory
```

无需参数。**直接执行，无需确认。**

## 行为

执行此命令会用 `markdown_templates/` 目录中的模板覆盖 workspace 目录下对应的 `.md` 文件。对于没有模板的现有 .md 文件，会清空其内容。

## 重置的文件

模板文件位于 `workspace/markdown_templates/`：
- AGENTS.md
- BOOTSTRAP.md
- HEARTBEAT.md
- IDENTITY.md
- SOUL.md
- TOOLS.md
- USER.md

以及其他所有模板目录中的 `.md` 文件。

## 注意事项

⚠️ 文件内容会被模板覆盖，当前会话的配置将丢失。
