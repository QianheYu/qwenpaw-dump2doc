#!/usr/bin/env python3
"""
qwenpaw dump2doc — 将 QwenPaw /dump_history 导出的 JSONL 对话历史转化为可读文档。

功能:
  - 输出 Markdown / HTML / 纯文本 三种格式
  - HTML 格式自动将 Markdown 文本渲染为富文本（通过 marked.js）
  - 系统消息、工具调用、thinking 默认折叠（可展开）
  - 支持角色过滤、紧凑模式等

用法:
    python3 dump2doc.py input.jsonl
    python3 dump2doc.py input.jsonl -o output.md
    python3 dump2doc.py input.jsonl -f html -o output.html
    python3 dump2doc.py input.jsonl -s -t --no-collapse
"""

import argparse
import json
import os
import re
import sys
import textwrap
from html import escape as html_escape
from typing import List, Optional


# ── 常量 ──────────────────────────────────────────────────

ROLE_LABEL = {
    "user": "👤 用户",
    "assistant": "🤖 助手",
    "system": "⚙️ 系统",
}

COLLAPSIBLE_TYPES = {"tool_use", "tool_result", "tool_error", "thinking"}
COLLAPSIBLE_ROLES = {"system"}


# ── 内容提取 / 分类 ──────────────────────────────────────

def extract_text(block: dict, labels: bool = True) -> str:
    """从一个 content block 提取可读文本。

    labels=True 时添加 [思考]/[调用工具] 等标记（纯文本/非折叠模式用）。
    labels=False 时返回裸文本（折叠模式下 summary 已标明类型）。
    """
    if isinstance(block, str):
        return block
    t = block.get("type", "")
    if t == "text":
        return block.get("text", "")
    elif t == "thinking":
        text = block.get("thinking", "")
        return f"[思考]\n{text}\n[/思考]" if labels else text
    elif t == "tool_use":
        name = block.get("name", "?")
        inp = block.get("input", {})
        inp_str = json.dumps(inp, ensure_ascii=False, indent=2) if inp else ""
        return f"[调用工具: {name}]\n{inp_str}\n[/调用工具]" if labels else inp_str
    elif t == "tool_result":
        name = block.get("name", "?")
        output = block.get("output", [])
        out_text = _extract_output_text(output)
        return f"[工具结果: {name}]\n{out_text}\n[/工具结果]" if labels else out_text
    elif t == "tool_error":
        return f"[工具错误]\n{block.get('error', '')}\n[/工具错误]" if labels else block.get("error", "")
    return ""


def block_summary(block: dict) -> str:
    """生成 block 的摘要标题（用于折叠的 summary）。"""
    if isinstance(block, str):
        return "文本"
    t = block.get("type", "")
    if t == "thinking":
        thinking = block.get("thinking", "")
        preview = thinking[:60].replace("\n", " ").strip()
        return f"💭 思考: {preview}…" if len(thinking) > 60 else f"💭 思考: {preview}"
    elif t == "tool_use":
        name = block.get("name", "?")
        return f"🔧 调用工具: {name}"
    elif t == "tool_result":
        name = block.get("name", "?")
        return f"📋 工具结果: {name}"
    elif t == "tool_error":
        return f"❌ 工具错误"
    return ""


def _extract_output_text(output: list) -> str:
    """提取 tool_result 中的文本内容。"""
    texts = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(item.get("text", ""))
    result = "\n".join(texts)
    if len(result) > 3000:
        result = result[:3000] + "\n…[已截断]"
    return result


def is_all_collapsible(blocks: list) -> bool:
    """判断消息的所有 content block 是否都是可折叠类型（无实质性文本回复）。"""
    for block in blocks:
        if isinstance(block, str):
            return False
        t = block.get("type", "")
        if t == "text":
            # 极短文本（如 "Searching memory..."）也视为非正式
            text = block.get("text", "").strip()
            if len(text) > 80:
                return False
        elif t not in COLLAPSIBLE_TYPES:
            return False
    return True


# ── 文档生成器 ────────────────────────────────────────────

class DocGenerator:
    """将 JSONL 对话历史转换为格式化文档。"""

    def __init__(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        fmt: str = "markdown",
        title: str = "",
        include_system: bool = False,
        include_tools: bool = False,
        include_thinking: bool = False,
        roles: Optional[List[str]] = None,
        show_timestamp: bool = True,
        show_role_label: bool = True,
        compact: bool = False,
        collapse: bool = True,
        md_render: bool = True,
    ):
        self.input_path = input_path
        self.output_path = output_path
        self.fmt = fmt
        self.title = title or os.path.splitext(os.path.basename(input_path))[0]
        self.include_system = include_system
        self.include_tools = include_tools
        self.include_thinking = include_thinking
        self.roles = set(roles) if roles else None
        self.show_timestamp = show_timestamp
        self.show_role_label = show_role_label
        self.compact = compact
        self.collapse = collapse
        self.md_render = md_render

        self._messages: List[dict] = []

    # ── 读取 ───────────────────────────────────────────

    def load(self) -> None:
        with open(self.input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                self._messages.append(obj)

    # ── 过滤 ───────────────────────────────────────────

    def _should_include(self, msg: dict) -> bool:
        role = msg.get("role", "")
        if self.roles and role not in self.roles:
            return False
        if role == "system" and not self.include_system:
            return False
        return True

    @staticmethod
    def _normalize_block(block) -> dict:
        if isinstance(block, str):
            return {"type": "text", "text": block}
        return block

    def _filter_content(self, blocks: list) -> list:
        result = []
        for block in blocks:
            block = self._normalize_block(block)
            t = block.get("type", "")
            if t == "thinking" and not self.include_thinking:
                continue
            if t in ("tool_use", "tool_result", "tool_error") and not self.include_tools:
                continue
            result.append(block)
        return result

    # ── 生成入口 ───────────────────────────────────────

    def generate(self) -> str:
        if not self._messages:
            self.load()

        if self.fmt == "markdown":
            return self._gen_markdown()
        elif self.fmt == "html":
            return self._gen_html()
        elif self.fmt == "text":
            return self._gen_text()
        else:
            raise ValueError(f"不支持的格式: {self.fmt}")

    def _get_time_range(self) -> tuple:
        first_ts = ""
        last_ts = ""
        for m in self._messages:
            ts = m.get("timestamp", "")
            if ts and not first_ts:
                first_ts = ts
            last_ts = ts or last_ts
        return first_ts, last_ts

    # ── Markdown 生成 ──────────────────────────────────

    def _gen_markdown(self) -> str:
        lines = []
        lines.append(f"# {self.title}")
        lines.append("")

        first_ts, last_ts = self._get_time_range()
        msg_count = sum(1 for m in self._messages if self._should_include(m))
        if first_ts:
            lines.append(f"> 导出时间范围: {first_ts[:10]} — {last_ts[:10]}  ")
            lines.append(f"> 消息总数: {len(self._messages)}（已筛选 {msg_count} 条）")
            if self.collapse:
                lines.append(f"> ⚙️ 系统消息与工具调用默认折叠，点击展开")
            lines.append("")

        last_role = ""
        for msg in self._messages:
            if not self._should_include(msg):
                continue
            role = msg.get("role", "?")
            ts = msg.get("timestamp", "")
            content_blocks = self._filter_content(msg.get("content", []))

            if not content_blocks:
                continue

            label = ROLE_LABEL.get(role, role)
            should_collapse_msg = self.collapse and role in COLLAPSIBLE_ROLES

            # ── 输出消息 ──
            if should_collapse_msg:
                # 整条 system 消息折叠
                ts_str = f" {ts[:19]}" if self.show_timestamp and ts else ""
                lines.append(f"<details>")
                lines.append(f"<summary>{html_escape(label)}{html_escape(ts_str)}</summary>")
                lines.append("")
                for block in content_blocks:
                    t = block.get("type", "")
                    text = extract_text(block, labels=False)
                    if text.strip():
                        lines.append(text)
                        lines.append("")
                lines.append("</details>")
                lines.append("")
            else:
                # 正常消息：角色标题
                if role != last_role or self.compact:
                    if role == "user":
                        lines.append(f"### {label}")
                    elif role == "assistant":
                        lines.append(f"#### {label}")
                    else:
                        lines.append(f"##### {label}")
                    last_role = role

                if self.show_timestamp and ts and not self.compact:
                    lines.append(f"*{ts[:19]}*  ")
                elif self.show_timestamp and ts and self.compact:
                    lines.append(f"*{ts[:19]}*")

                for block in content_blocks:
                    t = block.get("type", "")
                    should_collapse_block = (
                        self.collapse and t in COLLAPSIBLE_TYPES
                    )
                    text = extract_text(block, labels=not should_collapse_block)
                    if not text.strip():
                        continue

                    if should_collapse_block:
                        summary = block_summary(block)
                        lines.append(f"<details>")
                        lines.append(f"<summary>{html_escape(summary)}</summary>")
                        lines.append("")
                        lines.append(text)
                        lines.append("")
                        lines.append("</details>")
                    else:
                        lines.append(text)

                    if not self.compact:
                        lines.append("")

                if not self.compact:
                    lines.append("---")
                    lines.append("")

        return "\n".join(lines)

    # ── HTML 生成（聊天气泡风格 v3 — 轮次分组 + 自适应宽度）──

    def _gen_html(self) -> str:
        parts = []

        # ── Head ──
        parts.append("<!DOCTYPE html>")
        parts.append('<html lang="zh-CN" data-theme="light">')
        parts.append("<head>")
        parts.append('<meta charset="utf-8">')
        parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
        parts.append(f"<title>{html_escape(self.title)}</title>")

        if self.md_render:
            parts.append(
                '<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js">'
                '</script>'
            )

        parts.append("<style>")
        parts.append(self._html_css())
        parts.append("</style>")
        parts.append("</head>")
        parts.append("<body>")

        # ── Header ──
        first_ts, last_ts = self._get_time_range()
        msg_count = sum(1 for m in self._messages if self._should_include(m))
        parts.append("<header>")
        parts.append('<div class="header-content">')
        parts.append('<div class="header-title">')
        parts.append(f"<h1>{html_escape(self.title)}</h1>")
        meta_parts = []
        if first_ts:
            meta_parts.append(f"{first_ts[:10]} — {last_ts[:10]}")
        meta_parts.append(f"{msg_count} 条消息")
        if self.collapse:
            meta_parts.append("中间步骤默认折叠")
        parts.append(f"<p>{' · '.join(meta_parts)}</p>")
        parts.append('</div>')
        parts.append(
            '<button class="theme-toggle" onclick="toggleTheme()" '
            'title="切换深色模式">🌙</button>'
        )
        parts.append('</div>')
        parts.append("</header>")

        # ── Chat Container ──
        parts.append('<div class="chat-container">')

        # ── 按「轮次」分组并渲染 ──
        turns = self._build_turns()
        for turn in turns:
            parts.append(self._render_turn(turn))

        parts.append('</div>')

        # ── JS ──
        parts.append("<script>")
        if self.md_render or self.collapse:
            parts.append(self._html_js())
        parts.append("</script>")

        parts.append("</body>")
        parts.append("</html>")
        return "\n".join(parts)

    # ── 轮次构建 ───────────────────────────────────────

    def _build_turns(self) -> list:
        """将消息按用户消息为边界划分为轮次。

        每轮 = {
            'user_msg': dict or None,
            'messages': [msg_dict, ...],   # 后续所有消息（助手/系统）
        }
        """
        turns = []
        current = {"user_msg": None, "messages": []}

        for msg in self._messages:
            if not self._should_include(msg):
                continue
            role = msg.get("role", "")

            if role == "user":
                if current["user_msg"] is not None or current["messages"]:
                    turns.append(current)
                current = {"user_msg": msg, "messages": []}
            else:
                current["messages"].append(msg)

        if current["user_msg"] is not None or current["messages"]:
            turns.append(current)

        return turns

    # ── 轮次渲染 ───────────────────────────────────────

    def _is_substantive(self, msg: dict) -> bool:
        """判断消息是否有实质性的文本内容（而非仅思考/工具调用/短确认）。"""
        role = msg.get("role", "")
        if role != "assistant":
            return False
        blocks = self._filter_content(msg.get("content", []))
        if not blocks:
            return False
        for b in blocks:
            b = self._normalize_block(b)
            if b.get("type") == "text":
                text = b.get("text", "").strip()
                if len(text) > 10:
                    return True
        return False

    def _render_turn(self, turn: dict) -> str:
        """渲染一轮对话。

        连续的无实质内容的消息合并为中间步骤组（折叠），
        有实质文本的助手消息单独渲染为可见气泡。
        """
        parts = []

        # 用户消息
        if turn["user_msg"]:
            msg = turn["user_msg"]
            ts = msg.get("timestamp", "")
            blocks = self._filter_content(msg.get("content", []))
            parts.append(self._html_user_msg(ts, blocks))

        # 遍历后续消息：连续的无实质内容消息合并为中间步骤组
        buffer = []
        for msg in turn["messages"]:
            if self._is_substantive(msg):
                if buffer:
                    parts.append(self._html_intermediate_group(buffer))
                    buffer = []
                role = msg.get("role", "")
                ts = msg.get("timestamp", "")
                blocks = self._filter_content(msg.get("content", []))
                if role == "system":
                    label = ROLE_LABEL.get(role, role)
                    parts.append(self._html_system_msg(label, ts, blocks, collapsed=self.collapse))
                elif role == "assistant":
                    parts.append(self._html_assistant_msg(ts, blocks))
            else:
                buffer.append(msg)

        if buffer:
            parts.append(self._html_intermediate_group(buffer))

        return "\n".join(parts)

    def _html_intermediate_group(self, messages: list) -> str:
        """生成中间步骤的父级折叠组（与助手气泡对齐）。"""
        if not messages:
            return ""

        # 统计摘要
        count_parts = []
        think_count = 0
        tool_count = 0
        sys_count = 0
        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                sys_count += 1
            elif role == "assistant":
                blocks = self._filter_content(msg.get("content", []))
                for b in blocks:
                    b = self._normalize_block(b)
                    t = b.get("type", "")
                    if t == "thinking":
                        think_count += 1
                    elif t in ("tool_use", "tool_result"):
                        tool_count += 1

        summary_items = []
        if think_count:
            summary_items.append(f"{think_count} 次思考")
        if tool_count:
            summary_items.append(f"{tool_count} 次工具")
        if sys_count:
            summary_items.append(f"{sys_count} 条系统")
        summary = " · ".join(summary_items) if summary_items else f"{len(messages)} 条消息"

        parts = []
        if self.collapse:
            # 复用 .message.ai 的 flex 布局 + 隐藏 avatar，保证与气泡完全对齐
            parts.append('<div class="intermediate-group">')
            parts.append('<div class="avatar" aria-hidden="true">🤖</div>')
            parts.append('<div class="bubble-wrap">')
            parts.append(f'<details class="intermediate-details" open>')
            parts.append(f'<summary>🔍 中间步骤: {html_escape(summary)}</summary>')
            parts.append('<div class="intermediate-body">')

        for msg in messages:
            role = msg.get("role", "")
            ts = msg.get("timestamp", "")
            blocks = self._filter_content(msg.get("content", []))

            if not blocks:
                continue

            if role == "system":
                label = ROLE_LABEL.get(role, role)
                parts.append(self._html_system_msg(label, ts, blocks, collapsed=self.collapse))
            elif role == "assistant":
                parts.append(self._html_assistant_msg(ts, blocks, force_collapse=self.collapse))
            else:
                label = ROLE_LABEL.get(role, role)
                parts.append(self._html_system_msg(label, ts, blocks, collapsed=self.collapse))

        if self.collapse:
            parts.append('</div>')
            parts.append('</details>')
            parts.append('</div>')
            parts.append('</div>')

        return "\n".join(parts)

    def _html_css(self) -> str:
        return textwrap.dedent("""\
            :root {
                --bg: #edeef0;
                --surface: #ffffff;
                --text: #1a1a1e;
                --sub: #8e8e93;
                --bubble-user: #a8d8b9;
                --bubble-user-text: #1a3a28;
                --bubble-ai: #ffffff;
                --bubble-ai-text: #1a1a1e;
                --border: #d1d1d6;
                --code-bg: #1e1e1e;
                --code-text: #d4d4d4;
                --tool-bg: #f5f5f7;
                --thinking-bg: #fffde7;
                --shadow: 0 1px 2px rgba(0,0,0,.06);
            }
            [data-theme="dark"] {
                --bg: #1b1b24;
                --surface: #252532;
                --text: #e4e4ec;
                --sub: #9898a4;
                --bubble-user: #5c8f6b;
                --bubble-user-text: #e0f0e4;
                --bubble-ai: #2e2e3c;
                --bubble-ai-text: #e4e4ec;
                --border: #3c3c4a;
                --tool-bg: #22222e;
                --thinking-bg: #2d2a1a;
                --shadow: 0 1px 2px rgba(0,0,0,.3);
            }
            * { margin:0; padding:0; box-sizing:border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                             "Noto Sans SC", sans-serif;
                background: var(--bg); color: var(--text);
                line-height: 1.6; transition: background .3s, color .3s;
            }

            /* Header */
            header {
                background: var(--surface); border-bottom: 1px solid var(--border);
                padding: 14px 20px; position: sticky; top: 0; z-index: 100;
                box-shadow: 0 2px 10px rgba(0,0,0,.05);
            }
            .header-content {
                max-width: 800px; margin: 0 auto;
                display: flex; justify-content: space-between; align-items: center;
            }
            .header-title h1 { font-size: 18px; font-weight: 600; }
            .header-title p { font-size: 12px; color: var(--sub); margin-top: 2px; }
            .theme-toggle {
                background: none; border: 1px solid var(--border);
                border-radius: 20px; padding: 5px 15px; cursor: pointer;
                color: var(--text); font-size: 14px; transition: all .2s;
            }
            .theme-toggle:hover { background: var(--bubble-ai); }

            /* Chat */
            .chat-container { max-width: 1000px; margin: 16px auto; padding: 0 24px 60px; }

            /* Messages */
            .message { display: flex; margin-bottom: 24px; gap: 12px; }
            .message.user { flex-direction: row-reverse; }
            .message.system { justify-content: center; margin-bottom: 12px; }
            .avatar {
                width: 36px; height: 36px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                font-size: 18px; flex-shrink: 0;
                background: var(--bubble-ai); color: var(--text);
            }
            .message.user .avatar { background: var(--bubble-ai); color: var(--text); }
            .bubble-wrap { max-width: 78%; min-width: 60px; flex: 0 1 auto; position: relative; }
            .message.user .bubble-wrap { text-align: right; }
            .bubble {
                padding: 12px 16px; border-radius: 18px;
                word-wrap: break-word; overflow-wrap: break-word;
                position: relative;
            }
            .message.ai .bubble {
                background: var(--bubble-ai); color: var(--bubble-ai-text);
                box-shadow: var(--shadow);
            }
            .message.user .bubble {
                background: var(--bubble-user); color: var(--bubble-user-text);
            }

            /* 气泡下方复制按钮 */
            .copy-below {
                display: inline-block; margin-top: 6px;
                background: none; border: 1px solid var(--border);
                padding: 4px 12px; border-radius: 6px;
                font-size: 12px; cursor: pointer;
                color: var(--sub); font-family: inherit;
                opacity: .7; transition: all .15s;
            }
            .copy-below:hover { opacity: 1; background: var(--tool-bg); color: var(--text); }
            .copy-below.copied { color: #4caf50 !important; border-color: #4caf50 !important; opacity: 1; }
            .message-time {
                font-size: 11px; color: var(--sub); margin-top: 4px;
                padding: 0 4px;
            }
            .message.user .message-time { text-align: right; }

            /* 中间步骤父级折叠 — 复用 .message.ai flex 布局对齐 */
            .intermediate-group {
                display: flex; margin: 6px 0 18px; gap: 12px;
            }
            .intermediate-group .avatar {
                opacity: 0; pointer-events: none;
            }
            .intermediate-group .bubble-wrap {
                width: 100%;
                flex: 0 0 auto;
                overflow: hidden;
            }
            .intermediate-details {
                border: 1px dashed var(--border); border-radius: 10px;
                overflow: hidden;
            }
            .intermediate-details > summary {
                cursor: pointer; user-select: none; padding: 10px 16px;
                font-size: 13px; color: var(--sub); font-weight: 500;
                background: var(--surface); list-style: none;
            }
            .intermediate-details > summary::-webkit-details-marker { display: none; }
            .intermediate-details > summary:hover { background: var(--tool-bg); }
            .intermediate-body {
                padding: 8px 0 4px;
                background: var(--tool-bg);
                border-top: 1px solid var(--border);
            }
            .intermediate-body .message.system {
                justify-content: flex-start;
            }

            /* System collapse */
            .system-details {
                width: 100%; max-width: 600px;
                border: 1px dashed var(--border); border-radius: 8px;
                overflow: hidden;
            }
            .system-details > summary {
                cursor: pointer; user-select: none; padding: 8px 14px;
                font-size: 12px; color: var(--sub); font-weight: 500;
                background: var(--surface);
                display: flex; align-items: center; gap: 6px;
            }
            .system-details > summary:hover { background: var(--tool-bg); }
            .system-details .system-body {
                padding: 10px 14px; font-size: 12px;
                font-family: 'SF Mono', 'Cascadia Code', monospace;
                white-space: pre-wrap; overflow-x: auto;
                max-height: 300px; overflow-y: auto;
                background: var(--tool-bg); color: var(--sub);
                border-top: 1px solid var(--border);
            }

            /* In-bubble tool blocks */
            .tool-details { margin-top: 8px; }
            .tool-details > summary {
                cursor: pointer; user-select: none; padding: 5px 10px;
                font-size: 12px; color: var(--sub);
                background: var(--tool-bg); border-radius: 6px;
                border: 1px solid var(--border); display: inline-block;
            }
            .tool-details > summary:hover { opacity: .8; }
            .tool-body {
                margin-top: 4px; padding: 8px 10px;
                font-family: 'SF Mono', 'Cascadia Code', monospace;
                font-size: 11px; white-space: pre-wrap; overflow-x: auto;
                background: var(--tool-bg); border: 1px solid var(--border);
                border-radius: 6px; max-height: 250px; overflow-y: auto;
                color: var(--text);
            }
            .tool-body.thinking {
                background: var(--thinking-bg); border-style: dashed;
                font-family: inherit; font-style: italic;
            }

            /* Markdown inside bubbles */
            .bubble-content h1, .bubble-content h2, .bubble-content h3 {
                margin: 8px 0 4px; font-size: 1.05em;
            }
            .bubble-content p { margin: 4px 0; }
            .bubble-content pre {
                background: var(--code-bg); color: var(--code-text);
                padding: 12px; border-radius: 8px; overflow-x: auto;
                font-size: .85em; margin: 8px 0; position: relative;
            }
            .bubble-content code {
                background: rgba(0,0,0,.06); padding: 2px 5px;
                border-radius: 4px; font-size: .9em;
            }
            [data-theme="dark"] .bubble-content code {
                background: rgba(255,255,255,.1);
            }
            .bubble-content pre code { background: none; padding: 0; }
            .bubble-content table {
                border-collapse: collapse; width: 100%; margin: 8px 0;
                font-size: .9em;
            }
            .bubble-content th, .bubble-content td {
                border: 1px solid var(--border); padding: 6px 10px; text-align: left;
            }
            .bubble-content th { background: var(--tool-bg); }
            .bubble-content blockquote {
                border-left: 3px solid var(--border); margin: 6px 0;
                padding: 2px 12px; color: var(--sub);
            }
            .bubble-content ul, .bubble-content ol { margin: 4px 0; padding-left: 20px; }
            .bubble-content hr { border: none; border-top: 1px solid var(--border); margin: 10px 0; }

            /* Code copy btn */
            .code-header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 6px 12px; font-size: 11px; color: #999;
                background: #2d2d2d; border-radius: 8px 8px 0 0;
            }
            [data-theme="dark"] .code-header { background: #1a1a1a; }
            .code-header + pre {
                margin-top: 0;
                border-radius: 0 0 8px 8px;
            }
            .copy-btn {
                background: none; border: 1px solid #666; color: #ccc;
                border-radius: 4px; padding: 2px 8px; cursor: pointer;
                font-size: 11px; transition: all .2s;
            }
            .copy-btn:hover { background: #444; }
            .copy-btn.copied { border-color: #4caf50; color: #4caf50; }

            @media (max-width: 600px) {
                .bubble-wrap { max-width: 90%; }
                .bubble { padding: 10px 14px; border-radius: 14px; }
                header { padding: 10px 14px; }
                .header-title h1 { font-size: 16px; }
                .chat-container { padding: 0 10px; }
            }
            @media (min-width: 1400px) {
                .chat-container { max-width: 1200px; }
                .bubble-wrap { max-width: 75%; }
            }
            @media (min-width: 2000px) {
                .chat-container { max-width: 1500px; }
                .bubble-wrap { max-width: 72%; }
            }
            @media (min-width: 2800px) {
                .chat-container { max-width: 1800px; }
                .bubble-wrap { max-width: 68%; }
            }
        """)

    def _html_js(self) -> str:
        """生成 JavaScript（marked 渲染 + 折叠 + 主题 + 复制按钮）。"""
        js = []
        js.append(textwrap.dedent("""\
            // === 主题切换 ===
            function toggleTheme() {
                var h = document.documentElement;
                var t = h.getAttribute('data-theme');
                var next = t === 'dark' ? 'light' : 'dark';
                h.setAttribute('data-theme', next);
                var btn = document.querySelector('.theme-toggle');
                btn.textContent = next === 'dark' ? '☀️' : '🌙';
                localStorage.setItem('dump2doc-theme', next);
            }
            (function() {
                var saved = localStorage.getItem('dump2doc-theme');
                if (saved) {
                    document.documentElement.setAttribute('data-theme', saved);
                    var btn = document.querySelector('.theme-toggle');
                    if (btn) btn.textContent = saved === 'dark' ? '☀️' : '🌙';
                }
            })();
        """))
        if self.md_render:
            js.append(textwrap.dedent("""\
                // === Markdown 渲染 ===
                (function() {
                    if (typeof marked === 'undefined') return;
                    marked.setOptions({ breaks: true, gfm: true });
                    document.querySelectorAll('.bubble-content').forEach(function(el) {
                        var raw = el.textContent || '';
                        // 跳过空内容
                        if (!raw.trim()) return;
                        try {
                            el.innerHTML = marked.parse(raw);
                            // 给代码块加 header + 复制按钮
                            el.querySelectorAll('pre').forEach(function(pre) {
                                var code = pre.querySelector('code');
                                var lang = '';
                                if (code && code.className) {
                                    var m = code.className.match(/language-(\\w+)/);
                                    if (m) lang = m[1];
                                }
                                var header = document.createElement('div');
                                header.className = 'code-header';
                                header.innerHTML = '<span>' + lang + '</span>' +
                                    '<button class="copy-btn" onclick="copyCode(this)">复制</button>';
                                pre.parentNode.insertBefore(header, pre);
                            });
                        } catch(e) {}
                    });
                })();
            """))
        if self.collapse:
            js.append(textwrap.dedent("""\
                // === 折叠：system + 中间步骤组 默认关闭 ===
                (function() {
                    document.querySelectorAll('.system-details[open], .intermediate-details[open]').forEach(function(d) {
                        d.removeAttribute('open');
                    });
                })();
            """))
        js.append(textwrap.dedent("""\
            // === 复制代码 ===
            function copyCode(btn) {
                var pre = btn.parentElement.nextElementSibling;
                var code = pre ? pre.textContent : '';
                navigator.clipboard.writeText(code).then(function() {
                    btn.textContent = '已复制';
                    btn.classList.add('copied');
                    setTimeout(function() {
                        btn.textContent = '复制';
                        btn.classList.remove('copied');
                    }, 2000);
                }).catch(function() {
                    btn.textContent = '失败';
                    setTimeout(function() { btn.textContent = '复制'; }, 2000);
                });
            }

            // === 气泡复制（下方按钮）===
            function copyBubble(btn) {
                var bubble = btn.parentElement.querySelector('.bubble');
                if (!bubble) return;
                var clone = bubble.cloneNode(true);
                var btns = clone.querySelectorAll('.copy-below');
                btns.forEach(function(b) { b.remove(); });
                var text = clone.textContent.trim();
                navigator.clipboard.writeText(text).then(function() {
                    btn.textContent = '已复制';
                    btn.classList.add('copied');
                    setTimeout(function() {
                        btn.textContent = '复制';
                        btn.classList.remove('copied');
                    }, 2000);
                }).catch(function() {
                    btn.textContent = '失败';
                    setTimeout(function() { btn.textContent = '复制'; }, 2000);
                });
            }

            // === 给每个气泡加下方复制按钮 ===
            (function() {
                document.querySelectorAll('.bubble').forEach(function(bubble) {
                    var btn = document.createElement('button');
                    btn.className = 'copy-below';
                    btn.textContent = '复制';
                    btn.setAttribute('onclick', 'copyBubble(this)');
                    bubble.parentNode.insertBefore(btn, bubble.nextSibling);
                });
            })();
        """))
        return "\n".join(js)

    # ── HTML 消息构建 ──────────────────────────────────

    def _html_system_msg(self, label: str, ts: str, blocks: list, collapsed: bool = True) -> str:
        """生成 system 消息条（折叠或展开）。"""
        ts_str = f" · {ts[:19]}" if self.show_timestamp and ts else ""
        body = []
        for b in blocks:
            text = extract_text(b, labels=False)
            if text.strip():
                body.append(html_escape(text.strip()))

        if not body:
            return ""

        body_text = "\n".join(body)

        if collapsed:
            parts = ['<div class="message system">']
            parts.append(f'<details class="system-details" open>')
            parts.append(f'<summary>{html_escape(label)}{ts_str}</summary>')
            parts.append(f'<div class="system-body">{body_text}</div>')
            parts.append('</details>')
            parts.append('</div>')
            return "\n".join(parts)
        else:
            # 展开模式：直接显示
            return (
                f'<div class="message system" style="opacity:.7;font-size:12px;'
                f'text-align:center;padding:4px;">'
                f'<span>{html_escape(label)}{ts_str}</span><br>'
                f'<span style="font-family:monospace;">{body_text}</span>'
                f'</div>'
            )

    def _html_user_msg(self, ts: str, blocks: list) -> str:
        """生成用户聊天气泡。"""
        parts = ['<div class="message user">']
        parts.append('<div class="avatar">👤</div>')
        parts.append('<div class="bubble-wrap">')
        for b in blocks:
            text = extract_text(b, labels=False)
            if text.strip():
                parts.append(f'<div class="bubble">{html_escape(text.strip())}</div>')
        if self.show_timestamp and ts:
            parts.append(f'<div class="message-time">{html_escape(ts[:19])}</div>')
        parts.append('</div>')
        parts.append('</div>')
        return "\n".join(parts)

    def _html_assistant_msg(self, ts: str, blocks: list, force_collapse: bool = False) -> str:
        """生成 AI 聊天气泡（含 Markdown 文本 + 可折叠工具块）。

        force_collapse=True 时所有工具/thinking 强制折叠（用于中间步骤组）。
        """
        parts = ['<div class="message ai">']
        parts.append('<div class="avatar">🤖</div>')
        parts.append('<div class="bubble-wrap">')

        # 分离文本块和工具块
        text_blocks = []
        tool_blocks = []
        for b in blocks:
            b = self._normalize_block(b)
            t = b.get("type", "text")
            if t == "text":
                text_blocks.append(b)
            else:
                tool_blocks.append(b)

        # 文本内容（合并后用 marked 渲染）
        if text_blocks:
            combined = "\n\n".join(
                b.get("text", "") for b in text_blocks if b.get("text", "").strip()
            )
            if combined.strip():
                parts.append(
                    '<div class="bubble">'
                    f'<div class="bubble-content">{html_escape(combined)}</div>'
                    '</div>'
                )

        # 工具块
        for b in tool_blocks:
            t = b.get("type", "")
            should_collapse = force_collapse or (self.collapse and t in COLLAPSIBLE_TYPES)
            summary = html_escape(block_summary(b))
            if should_collapse:
                parts.append(f'<details class="tool-details">')
                parts.append(f'<summary>{summary}</summary>')
                parts.append(self._html_tool_body(b, t))
                parts.append('</details>')
            else:
                parts.append(self._html_tool_body(b, t))

        if self.show_timestamp and ts:
            parts.append(f'<div class="message-time">{html_escape(ts[:19])}</div>')

        parts.append('</div>')
        parts.append('</div>')
        return "\n".join(parts)

    def _html_tool_body(self, block: dict, t: str) -> str:
        """生成工具/thinking 块的内容体。"""
        if t == "thinking":
            text = html_escape(block.get("thinking", ""))
            return f'<div class="tool-body thinking">{text}</div>'
        elif t == "tool_use":
            name = block.get("name", "?")
            inp = block.get("input", {})
            inp_str = json.dumps(inp, ensure_ascii=False, indent=2) if inp else ""
            text = html_escape(f"{name}\n{inp_str}")
            return f'<div class="tool-body">{text}</div>'
        elif t == "tool_result":
            name = block.get("name", "?")
            out_text = _extract_output_text(block.get("output", []))
            text = html_escape(f"{name}\n{out_text}")
            return f'<div class="tool-body">{text}</div>'
        elif t == "tool_error":
            text = html_escape(block.get("error", ""))
            return f'<div class="tool-body" style="color:#e53935;">{text}</div>'
        return ""

    # ── 纯文本 ─────────────────────────────────────────

    def _gen_text(self) -> str:
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"  {self.title}")
        lines.append(f"{'='*60}")
        lines.append("")

        for msg in self._messages:
            if not self._should_include(msg):
                continue
            role = msg.get("role", "?")
            ts = msg.get("timestamp", "")
            content_blocks = self._filter_content(msg.get("content", []))

            if not content_blocks:
                continue

            label = ROLE_LABEL.get(role, role)
            header = f"[{label}]"
            if self.show_timestamp and ts:
                header += f" {ts[:19]}"
            lines.append(header)
            lines.append("-" * 40)

            for block in content_blocks:
                t = block.get("type", "")
                if self.collapse and t in COLLAPSIBLE_TYPES:
                    summary = block_summary(block)
                    lines.append(f"  [{summary}]")
                    lines.append("  " + "-" * 20)
                    text = extract_text(block, labels=False)
                    for txt_line in text.strip().split("\n"):
                        lines.append(f"  {txt_line}")
                    lines.append("  " + "-" * 20)
                else:
                    text = extract_text(block)
                    if text.strip():
                        lines.append(text.strip())
                lines.append("")
            lines.append("")
        return "\n".join(lines)

    # ── 输出 ───────────────────────────────────────────

    def run(self) -> str:
        doc = self.generate()
        if self.output_path:
            os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(doc)
            print(f"✅ 已生成: {self.output_path}", file=sys.stderr)
            print(f"   格式: {self.fmt}, 大小: {len(doc)} 字符", file=sys.stderr)
        else:
            sys.stdout.write(doc)
        return doc


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="将 QwenPaw /dump_history JSONL 导出转为可读文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              %(prog)s debug_history.jsonl
              %(prog)s debug_history.jsonl -o 对话记录.md
              %(prog)s debug_history.jsonl -f html -o 对话记录.html
              %(prog)s debug_history.jsonl -s -t            # 含 system+工具
              %(prog)s debug_history.jsonl -s -t --no-collapse  # 不折叠
              %(prog)s debug_history.jsonl --role user,assistant -c  # 精简
        """),
    )
    parser.add_argument("input", help="JSONL 输入文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("-f", "--format", default="markdown",
                        choices=["markdown", "html", "text"],
                        help="输出格式 (默认: markdown)")
    parser.add_argument("--title", default="", help="文档标题（默认取文件名）")
    parser.add_argument("-s", "--include-system", action="store_true",
                        help="包含 system 角色的消息")
    parser.add_argument("-t", "--include-tools", action="store_true",
                        help="包含工具调用和结果 (tool_use / tool_result)")
    parser.add_argument("-w", "--include-thinking", action="store_true",
                        help="包含 thinking 内容")
    parser.add_argument("--role", default="",
                        help="仅保留指定角色，逗号分隔 (如 user,assistant)")
    parser.add_argument("--no-timestamp", action="store_true", help="不显示时间戳")
    parser.add_argument("--no-role-label", action="store_true", help="不显示角色标签")
    parser.add_argument("-c", "--compact", action="store_true", help="紧凑模式，减少空行")
    parser.add_argument("--no-collapse", action="store_true",
                        help="禁用折叠功能（全部展开）")
    parser.add_argument("--no-md-render", action="store_true",
                        help="禁用 HTML 中的 Markdown 渲染")

    args = parser.parse_args()

    roles = [r.strip() for r in args.role.split(",") if r.strip()] if args.role else None

    gen = DocGenerator(
        input_path=args.input,
        output_path=args.output,
        fmt=args.format,
        title=args.title,
        include_system=args.include_system,
        include_tools=args.include_tools,
        include_thinking=args.include_thinking,
        roles=roles,
        show_timestamp=not args.no_timestamp,
        show_role_label=not args.no_role_label,
        compact=args.compact,
        collapse=not args.no_collapse,
        md_render=not args.no_md_render,
    )
    gen.run()


if __name__ == "__main__":
    main()
