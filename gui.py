#!/usr/bin/env python3
"""
QwenPaw dump2doc GUI — 带图形界面的聊天记录转换工具。

用法：
    python3 gui.py

依赖：
    - tkinter（Python 标准库自带）
    - dump2doc.py（同目录下的核心引擎）
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# 确保可以导入同目录的 dump2doc 模块
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from dump2doc import DocGenerator


# ── 主界面 ────────────────────────────────────────────────

class Dump2DocGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("qwenpaw dump2doc — QwenPaw聊天记录转换工具")
        self.root.geometry("820x680")
        self.root.minsize(640, 520)

        # 样式
        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()
        self._update_output_path()

    # ── UI 构建 ───────────────────────────────────────

    def _build_ui(self):
        # ── 主布局 ──
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # ── 第 1 行：输入文件 ──
        row1 = ttk.Frame(main)
        row1.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row1, text="输入文件", width=10).pack(side=tk.LEFT)
        self.input_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.input_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(row1, text="浏览…", command=self._browse_input).pack(side=tk.RIGHT)

        # ── 第 2 行：输出文件 ──
        row2 = ttk.Frame(main)
        row2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row2, text="输出文件", width=10).pack(side=tk.LEFT)
        self.output_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(row2, text="浏览…", command=self._browse_output).pack(side=tk.RIGHT)

        # ── 第 3 行：格式选择 ──
        row3 = ttk.Frame(main)
        row3.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row3, text="输出格式", width=10).pack(side=tk.LEFT)
        self.format_var = tk.StringVar(value="markdown")
        fmt_frame = ttk.Frame(row3)
        fmt_frame.pack(side=tk.LEFT, padx=4)
        for val, label in [("markdown", "Markdown"), ("html", "HTML 聊天"), ("text", "纯文本")]:
            ttk.Radiobutton(fmt_frame, text=label, variable=self.format_var, value=val,
                            command=self._update_output_path).pack(side=tk.LEFT, padx=(0, 12))

        # ── 分隔线 ──
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # ── 选项区域 ──
        opts_label = ttk.LabelFrame(main, text="选项", padding=8)
        opts_label.pack(fill=tk.X, pady=(0, 8))

        # 行 A
        opt_a = ttk.Frame(opts_label)
        opt_a.pack(fill=tk.X, pady=2)
        self.include_system_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_a, text="包含系统消息", variable=self.include_system_var).pack(side=tk.LEFT, padx=(0, 16))
        self.include_tools_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_a, text="包含工具调用", variable=self.include_tools_var).pack(side=tk.LEFT, padx=(0, 16))
        self.include_thinking_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_a, text="包含思考过程", variable=self.include_thinking_var).pack(side=tk.LEFT, padx=(0, 16))
        self.compact_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_a, text="紧凑模式", variable=self.compact_var).pack(side=tk.LEFT)

        # 行 B
        opt_b = ttk.Frame(opts_label)
        opt_b.pack(fill=tk.X, pady=2)
        self.collapse_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_b, text="折叠系统/工具消息", variable=self.collapse_var).pack(side=tk.LEFT, padx=(0, 16))
        self.md_render_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_b, text="HTML 中渲染 Markdown", variable=self.md_render_var).pack(side=tk.LEFT, padx=(0, 16))
        self.show_ts_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_b, text="显示时间戳", variable=self.show_ts_var).pack(side=tk.LEFT)

        # 行 C：角色过滤
        opt_c = ttk.Frame(opts_label)
        opt_c.pack(fill=tk.X, pady=2)
        ttk.Label(opt_c, text="角色过滤:").pack(side=tk.LEFT, padx=(0, 6))
        self.role_var = tk.StringVar(value="")
        for val, label in [("", "全部"), ("user,assistant", "用户+助手"), ("user", "仅用户"), ("assistant", "仅助手")]:
            ttk.Radiobutton(opt_c, text=label, variable=self.role_var, value=val).pack(side=tk.LEFT, padx=(0, 10))

        # ── 操作按钮 ──
        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(4, 8))
        self.preview_btn = ttk.Button(btn_row, text="预览 ⚡", command=self._do_preview)
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.convert_btn = ttk.Button(btn_row, text="转换 🚀", command=self._do_convert)
        self.convert_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.open_btn = ttk.Button(btn_row, text="打开输出文件 📂", command=self._open_output, state=tk.DISABLED)
        self.open_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.progress = ttk.Progressbar(btn_row, mode="indeterminate", length=120)
        self.progress.pack(side=tk.RIGHT)

        # ── 日志/预览面板 ──
        self.log = scrolledtext.ScrolledText(main, wrap=tk.WORD, font=("Consolas", 11),
                                             bg="#fafafa", fg="#1a1a1a", relief=tk.SUNKEN, borderwidth=2)
        self.log.pack(fill=tk.BOTH, expand=True)

        self._log("✅ QwenPaw dump2doc GUI 就绪。请选择输入文件后点击「转换」或「预览」。")

    # ── 逻辑 ───────────────────────────────────────────

    def _log(self, text: str):
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="选择 JSONL 文件",
            filetypes=[("JSONL 文件", "*.jsonl"), ("所有文件", "*.*")],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self._update_output_path()

    def _browse_output(self):
        fmt = self.format_var.get()
        ext = {"markdown": ".md", "html": ".html", "text": ".txt"}[fmt]
        path = filedialog.asksaveasfilename(
            title="保存输出文件",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} 文件", f"*{ext}"), ("所有文件", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def _update_output_path(self):
        inp = self.input_var.get()
        if inp:
            base = os.path.splitext(os.path.basename(inp))[0]
            fmt = self.format_var.get()
            ext = {"markdown": ".md", "html": ".html", "text": ".txt"}[fmt]
            out_dir = os.path.dirname(inp) or "."
            self.output_var.set(os.path.join(out_dir, f"{base}_export{ext}"))

    def _get_generator(self) -> DocGenerator:
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        role_str = self.role_var.get().strip()
        roles = [r.strip() for r in role_str.split(",") if r.strip()] if role_str else None

        return DocGenerator(
            input_path=inp,
            output_path=out,
            fmt=self.format_var.get(),
            title="",
            include_system=self.include_system_var.get(),
            include_tools=self.include_tools_var.get(),
            include_thinking=self.include_thinking_var.get(),
            roles=roles,
            show_timestamp=self.show_ts_var.get(),
            show_role_label=True,
            compact=self.compact_var.get(),
            collapse=self.collapse_var.get(),
            md_render=self.md_render_var.get(),
        )

    def _validate(self) -> bool:
        inp = self.input_var.get().strip()
        if not inp:
            messagebox.showwarning("缺少输入", "请先选择 JSONL 输入文件。")
            return False
        if not os.path.isfile(inp):
            messagebox.showerror("文件不存在", f"找不到文件:\n{inp}")
            return False
        return True

    # ── 转换线程 ──────────────────────────────────────

    def _run_in_thread(self, target, *args):
        self.progress.start(10)
        self.convert_btn.config(state=tk.DISABLED)
        self.preview_btn.config(state=tk.DISABLED)

        def runner():
            try:
                target(*args)
            finally:
                self.root.after(0, self._task_done)

        threading.Thread(target=runner, daemon=True).start()

    def _task_done(self):
        self.progress.stop()
        self.convert_btn.config(state=tk.NORMAL)
        self.preview_btn.config(state=tk.NORMAL)

    # ── 操作 ───────────────────────────────────────────

    def _do_preview(self):
        if not self._validate():
            return
        gen = self._get_generator()
        gen.output_path = None
        self._run_in_thread(self._preview_thread, gen)

    def _preview_thread(self, gen: DocGenerator):
        try:
            doc = gen.generate()
            preview = doc[:15000]
            if len(doc) > 15000:
                preview += "\n\n… [已截断，完整内容请导出到文件]"
            self.root.after(0, self._show_preview, preview)
            self.root.after(0, self._log, f"📄 预览: {len(doc)} 字符")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 预览失败: {e}")

    def _show_preview(self, text: str):
        self.log.delete("1.0", tk.END)
        self.log.insert("1.0", text)

    def _do_convert(self):
        if not self._validate():
            return
        out = self.output_var.get().strip()
        if not out:
            messagebox.showwarning("缺少输出", "请指定输出文件路径。")
            return
        gen = self._get_generator()
        self._run_in_thread(self._convert_thread, gen)

    def _convert_thread(self, gen: DocGenerator):
        try:
            doc = gen.run()
            size_kb = os.path.getsize(gen.output_path) / 1024
            self.root.after(0, self._log,
                f"✅ 已生成: {gen.output_path} ({size_kb:.1f} KB, {len(doc)} 字符)")
            self.root.after(0, self._enable_open)
        except Exception as e:
            self.root.after(0, self._log, f"❌ 转换失败: {e}")

    def _enable_open(self):
        self.open_btn.config(state=tk.NORMAL)

    def _open_output(self):
        out = self.output_var.get().strip()
        if not out or not os.path.isfile(out):
            messagebox.showwarning("文件不存在", "请先执行转换生成文件。")
            return
        try:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(out)}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e))


# ── 入口 ──────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = Dump2DocGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
