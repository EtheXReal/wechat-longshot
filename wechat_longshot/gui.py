"""A minimal Tk window around the pipeline: pick a start point, press Start, get a PDF."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .cli import _parse_start


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("微信长截图")
        root.resizable(False, False)
        self.q: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        pad = {"padx": 12, "pady": 4}
        frm = ttk.Frame(root, padding=12)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="1. 在微信里打开要导出的聊天窗口", font=("", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **pad
        )

        ttk.Label(frm, text="2. 从哪里开始", font=("", 13, "bold")).grid(
            row=1, column=0, columnspan=3, sticky="w", **pad
        )
        self.mode = tk.StringVar(value="current")
        ttk.Radiobutton(
            frm, text="从当前画面开始，一直截到最新消息", variable=self.mode, value="current"
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=28)
        ttk.Radiobutton(frm, text="从指定时间开始：", variable=self.mode, value="time").grid(
            row=3, column=0, sticky="w", padx=28
        )
        self.start_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d 00:00"))
        ttk.Entry(frm, textvariable=self.start_var, width=18).grid(row=3, column=1, sticky="w")
        ttk.Label(frm, text="(格式 2026-09-01 10:00)").grid(row=3, column=2, sticky="w")

        ttk.Label(frm, text="3. 输出", font=("", 13, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", **pad
        )
        self.page_mode = tk.StringVar(value="long")
        ttk.Radiobutton(frm, text="一张长页 PDF", variable=self.page_mode, value="long").grid(
            row=5, column=0, sticky="w", padx=28
        )
        ttk.Radiobutton(frm, text="A4 分页 PDF", variable=self.page_mode, value="a4").grid(
            row=5, column=1, sticky="w"
        )
        self.out_var = tk.StringVar(value=str(self._default_out()))
        ttk.Entry(frm, textvariable=self.out_var, width=44).grid(
            row=6, column=0, columnspan=2, sticky="w", padx=28
        )
        ttk.Button(frm, text="选择…", command=self._choose_out).grid(row=6, column=2, sticky="w")

        self.start_btn = ttk.Button(frm, text="开始截图", command=self._start)
        self.start_btn.grid(row=7, column=0, columnspan=3, pady=12, ipadx=20, ipady=6)
        ttk.Label(frm, text="截图过程中请不要移动鼠标或操作键盘", foreground="#888").grid(
            row=8, column=0, columnspan=3
        )

        self.logbox = tk.Text(frm, height=10, width=64, state="disabled", font=("Menlo", 11))
        self.logbox.grid(row=9, column=0, columnspan=3, pady=(8, 0))

        root.after(100, self._drain)

    # -- helpers ------------------------------------------------------------------

    @staticmethod
    def _default_out() -> Path:
        desktop = Path.home() / "Desktop"
        base = desktop if desktop.is_dir() else Path.home()
        return base / f"微信长截图-{datetime.now():%Y%m%d-%H%M}.pdf"

    def _choose_out(self) -> None:
        cur = Path(self.out_var.get())
        path = filedialog.asksaveasfilename(
            initialdir=str(cur.parent),
            initialfile=cur.name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if path:
            self.out_var.set(path)

    def _log(self, msg: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _drain(self) -> None:
        try:
            while True:
                self._log(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # -- run ----------------------------------------------------------------------
    #
    # The capture runs in a *subprocess* (the CLI), not a thread: Apple's Vision OCR
    # deadlocks when called from a secondary Python thread while Tk owns the main one.

    def _start(self) -> None:
        args = [sys.executable, "-m", "wechat_longshot.cli", "--page-mode", self.page_mode.get()]
        if self.mode.get() == "time":
            try:
                start = _parse_start(self.start_var.get().strip())
            except Exception:
                messagebox.showerror("时间格式不对", "请用类似 2026-09-01 10:00 的格式")
                return
            args += ["--from", start.strftime("%Y-%m-%d %H:%M")]
        else:
            args += ["--from-current"]
        out = Path(self.out_var.get()).expanduser()
        args += ["-o", str(out)]

        self.start_btn.configure(state="disabled", text="截图中…")
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

        def work() -> None:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.q.put(line.rstrip())
            code = proc.wait()
            if code == 0 and out.exists():
                self.root.after(0, lambda: self._finished(out))
            else:
                self.root.after(0, lambda: self._finished(None, f"退出码 {code}，详情见上方日志"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _finished(self, result: Path | None, error: str | None = None) -> None:
        self.start_btn.configure(state="normal", text="开始截图")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        if result is not None:
            subprocess.run(["open", str(result)], check=False)
            self.out_var.set(str(self._default_out()))
        else:
            messagebox.showerror("截图失败", error or "未知错误")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
