# QwenPaw dump2doc

将 QwenPaw `/dump_history` 导出的 JSONL 对话历史转化为可读文档。

## 功能

- **3 种输出格式**：Markdown / HTML / 纯文本
- **HTML 自动渲染**：通过 marked.js 将 Markdown 文本转为富文本（表格、代码块、标题等）
- **智能折叠**：系统消息、工具调用、thinking 默认折叠，点击展开
- **角色过滤**：按需保留 user / assistant / system
- **紧凑模式**：减少空行，阅读更紧凑

## 快速上手

```bash
# 默认：Markdown 输出到 stdout（仅用户+助手消息）
python3 dump2doc.py debug_history.jsonl

# HTML 完整版（含 system + 工具 + thinking，折叠 + 渲染）
python3 dump2doc.py debug_history.jsonl -f html -s -t -w -o 完整记录.html

# 紧凑 Markdown（仅用户+助手对话）
python3 dump2doc.py debug_history.jsonl --role user,assistant -c -o 精简对话.md

# 关闭折叠（全部展开）
python3 dump2doc.py debug_history.jsonl -s -t --no-collapse -o 展开版.md

# 关闭 HTML 中的 Markdown 渲染（保留原始 Markdown 文本）
python3 dump2doc.py debug_history.jsonl -f html --no-md-render -o 纯文本.html
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `-o, --output` | 输出文件路径（默认 stdout） |
| `-f, --format` | 格式：`markdown` / `html` / `text` |
| `--title` | 文档标题（默认取文件名） |
| `-s, --include-system` | 包含 system 消息（默认折叠） |
| `-t, --include-tools` | 包含工具调用和结果（默认折叠） |
| `-w, --include-thinking` | 包含 thinking 内容（默认折叠） |
| `--role` | 筛选角色，逗号分隔（如 `user,assistant`） |
| `--no-timestamp` | 不显示时间戳 |
| `-c, --compact` | 紧凑模式 |
| `--no-collapse` | 禁用折叠（全部展开） |
| `--no-md-render` | 禁用 HTML 中的 Markdown 渲染 |

## 折叠规则

| 内容类型 | 默认行为 |
|----------|----------|
| 用户消息、助手文本回复 | 展开 |
| 系统消息（role=system） | 折叠 |
| 工具调用（tool_use） | 折叠 |
| 工具结果（tool_result） | 折叠 |
| 思考过程（thinking） | 折叠 |

Markdown 文件通过内嵌 `<details>` HTML 标签实现折叠，兼容 GitHub、VS Code、Obsidian 等主流渲染器。
