"""Small nontechnical Tkinter window for the manual Windows reader session."""

from __future__ import annotations

from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable
import webbrowser

from .controller import ReaderController, ReaderStatus


class _StatusPump:
    """Carry worker statuses to Tk without making any worker-side Tk call."""

    def __init__(
        self,
        window,
        apply_status: Callable[[ReaderStatus], None],
        *,
        interval_ms: int = 50,
    ) -> None:
        self._window = window
        self._apply_status = apply_status
        self._interval_ms = interval_ms
        self._queue: SimpleQueue[ReaderStatus] = SimpleQueue()
        self._closed = Event()

    def start(self) -> None:
        """Schedule the first drain; callers must invoke this on the UI thread."""
        if not self._closed.is_set():
            self._window.after(0, self._drain)

    def post(self, status: ReaderStatus) -> None:
        """Enqueue from any worker without waiting for or calling Tk."""
        if not self._closed.is_set():
            self._queue.put(status)

    def close(self) -> None:
        """Make queued and future updates harmless before the window is destroyed."""
        self._closed.set()

    def _drain(self) -> None:
        if self._closed.is_set():
            return
        while not self._closed.is_set():
            try:
                status = self._queue.get_nowait()
            except Empty:
                break
            self._apply_status(status)
        if not self._closed.is_set():
            self._window.after(self._interval_ms, self._drain)


def _stop_and_destroy(controller: ReaderController, window) -> None:
    """Always release the Tk window even when session cleanup needs a retry."""
    try:
        controller.stop()
    finally:
        window.destroy()


def run(root: Path, config_path: Path, program_path: Path, port: int = 8765) -> int:
    """Open the manual launcher and keep the reader alive until it closes."""
    serving_program = Path(program_path).resolve(strict=True)
    current_program = Path(sys.executable).resolve(strict=True)
    if serving_program != current_program or serving_program.name.casefold() != "pythonw.exe":
        raise ValueError("请通过“JLPT iPad 阅读器”桌面快捷方式启动（必须使用同一个 pythonw.exe）")

    window = tk.Tk()
    window.title("JLPT iPad 阅读器")
    window.geometry("560x300")
    window.minsize(520, 280)

    frame = ttk.Frame(window, padding=20)
    frame.grid(row=0, column=0, sticky="nsew")
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="JLPT iPad 只读阅读器", font=("Microsoft YaHei UI", 15, "bold")).grid(
        row=0, column=0, columnspan=4, sticky="w", pady=(0, 14)
    )
    status_var = tk.StringVar(value="正在准备……")
    ttk.Label(frame, textvariable=status_var, wraplength=510, justify="left").grid(
        row=1, column=0, columnspan=4, sticky="ew", pady=(0, 12)
    )
    ttk.Label(frame, text="访问地址").grid(row=2, column=0, columnspan=4, sticky="w")
    url_var = tk.StringVar(value="")
    url_entry = ttk.Entry(frame, textvariable=url_var, state="readonly", font=("Segoe UI", 11))
    url_entry.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 16))

    closing = False
    controller: ReaderController

    def copy_url() -> None:
        value = url_var.get()
        if not value:
            return
        window.clipboard_clear()
        window.clipboard_append(value)
        status_var.set("地址已复制。请在同一 Wi-Fi 的 iPad Safari 中打开。")

    def apply_status(status: ReaderStatus) -> None:
        status_var.set(status.message)
        url_var.set(status.url or "")
        if status.state == "running":
            firewall_button.grid_remove()
            firewall_button.configure(state="disabled")
        elif status.state == "configuring":
            firewall_button.configure(state="disabled")
        elif status.state not in {"preparing", "building", "stopped"}:
            firewall_button.grid()
            firewall_button.configure(state="normal")
        enabled = "normal" if status.url else "disabled"
        copy_button.configure(state=enabled)
        open_button.configure(state=enabled)

    status_pump = _StatusPump(window, apply_status)

    controller = ReaderController(
        root,
        config_path,
        serving_program,
        port=port,
        on_status=status_pump.post,
    )

    def configure_firewall_worker() -> None:
        controller.configure_firewall()

    def configure_firewall_clicked() -> None:
        approved = messagebox.askyesno(
            "配置专用网络访问",
            "此操作会请求 Windows 管理员确认，并只允许专用网络中的本地子网访问。\n\n"
            "不会开放公用网络，也不会修改资料文件。是否继续？",
            parent=window,
        )
        if approved:
            firewall_button.configure(state="disabled")
            Thread(target=configure_firewall_worker, name="jlpt-reader-firewall", daemon=True).start()

    def close_window() -> None:
        nonlocal closing
        if closing:
            return
        closing = True
        stop_button.configure(state="disabled")
        status_pump.close()
        _stop_and_destroy(controller, window)

    copy_button = ttk.Button(frame, text="复制地址", command=copy_url)
    open_button = ttk.Button(frame, text="在本机打开", command=lambda: webbrowser.open(url_var.get()))
    firewall_button = ttk.Button(frame, text="配置专用网络访问", command=configure_firewall_clicked)
    stop_button = ttk.Button(frame, text="停止服务", command=close_window)
    copy_button.grid(row=4, column=0, padx=(0, 8), sticky="ew")
    open_button.grid(row=4, column=1, padx=8, sticky="ew")
    firewall_button.grid(row=4, column=2, padx=8, sticky="ew")
    stop_button.grid(row=4, column=3, padx=(8, 0), sticky="ew")
    copy_button.configure(state="disabled")
    open_button.configure(state="disabled")
    window.protocol("WM_DELETE_WINDOW", close_window)
    status_pump.start()

    def start_worker() -> None:
        try:
            controller.start()
        except Exception as error:
            status_pump.post(ReaderStatus("error", f"启动失败：{error}"))

    Thread(target=start_worker, name="jlpt-reader-start", daemon=True).start()
    try:
        window.mainloop()
    finally:
        status_pump.close()
        controller.stop()
    return 0
