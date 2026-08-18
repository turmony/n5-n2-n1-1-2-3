"""Coordinate the disposable build, watcher, read-only server, and LAN boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Lock, RLock
from typing import Callable

from .builder import BuildResult, SiteStore, build_site
from .firewall import (
    configure_firewall as configure_firewall_rule,
    firewall_rule_present,
)
from .network import private_lan_addresses
from .server import ReadOnlyServer
from .watcher import SourceWatcher


@dataclass(frozen=True)
class ReaderStatus:
    """One user-visible launcher status update."""

    state: str
    message: str
    url: str | None = None


class ReaderController:
    """Own one manual reader session and all of its temporary resources."""

    def __init__(
        self,
        root: Path,
        config_path: Path,
        program_path: Path,
        port: int = 8765,
        on_status: Callable[[ReaderStatus], None] | None = None,
    ) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("端口必须是 1024 到 65535 之间的整数")
        self.root = Path(root).resolve(strict=False)
        self.config_path = Path(config_path).resolve(strict=False)
        self.program_path = Path(program_path).resolve(strict=True)
        self.port = port
        self._on_status = on_status or (lambda status: None)

        self._lifecycle_lock = RLock()
        self._build_lock = Lock()
        self._configuration_lock = Lock()
        self._temporary: TemporaryDirectory[str] | None = None
        self._store: SiteStore | None = None
        self._server: ReadOnlyServer | None = None
        self._watcher: SourceWatcher | None = None
        self._build_number = 0
        self._started = False
        self._starting = False
        self._stop_requested = False
        self._stopped_published = False
        self._addresses: tuple[str, ...] = ()
        self._lan_enabled = False
        self._network_reason = ""

    @property
    def urls(self) -> tuple[str, ...]:
        """Return every currently usable access URL, in preferred order."""
        with self._lifecycle_lock:
            if self._lan_enabled:
                return tuple(f"http://{address}:{self.port}" for address in self._addresses)
            return (self._local_url(),) if self._started else ()

    def start(self) -> bool:
        """Build and start one reader session; never configure the firewall."""
        self._validate_start_inputs()
        with self._lifecycle_lock:
            if self._started:
                return True
            if self._starting or self._stop_requested:
                return False
            self._starting = True

        self._publish(ReaderStatus("preparing", "正在准备只读阅读器……"))
        try:
            with self._build_lock:
                with self._lifecycle_lock:
                    if self._stop_requested:
                        return False
                temporary = TemporaryDirectory(prefix="jlpt-reader-")
                with self._lifecycle_lock:
                    cancelled = self._stop_requested
                if cancelled:
                    temporary.cleanup()
                    return False
                try:
                    store = SiteStore(Path(temporary.name))
                except Exception:
                    temporary.cleanup()
                    raise
                with self._lifecycle_lock:
                    if self._stop_requested:
                        cancelled = True
                    else:
                        cancelled = False
                        self._temporary = temporary
                        self._store = store
                if cancelled:
                    store.close()
                    temporary.cleanup()
                    return False

                self._publish(ReaderStatus("building", "正在生成阅读页面……"))
                result = self._next_build(store, Path(temporary.name))
            if not result.success:
                self._publish_build_error("首次构建失败", result)
                return False
            with self._lifecycle_lock:
                if self._stop_requested:
                    return False

            status = self._inspect_network()
            host = "0.0.0.0" if status.state == "running" else "127.0.0.1"
            try:
                server = ReadOnlyServer(store, host, self.port)
                server.start()
            except OSError as error:
                self._publish(
                    ReaderStatus(
                        "error",
                        f"无法启动端口 {self.port}；它可能已被其他程序占用。{error}",
                    )
                )
                return False

            watcher = SourceWatcher(
                self.root,
                self.rebuild,
                on_error=lambda message: self._publish(
                    ReaderStatus("error", f"资料更新监测出错：{message}", self._current_url())
                ),
            )
            with self._lifecycle_lock:
                if self._stop_requested:
                    server.stop()
                    return False
                self._server = server
                self._watcher = watcher
                self._started = True
            watcher.start()
            self._publish(self._network_status(reminder=True))
            return True
        except Exception as error:
            self._publish(ReaderStatus("error", f"阅读器启动失败：{type(error).__name__}: {error}"))
            raise
        finally:
            with self._lifecycle_lock:
                self._starting = False

    def rebuild(self) -> bool:
        """Publish one settled rebuild, or retain the current last-good site."""
        if not self._build_lock.acquire(blocking=False):
            return False
        try:
            with self._lifecycle_lock:
                store = self._store
                temporary = self._temporary
                started = self._started and not self._stop_requested
            if store is None or temporary is None or not started:
                return False

            self._publish(ReaderStatus("updating", "检测到资料变化，正在更新……", self._current_url()))
            result = self._next_build(store, Path(temporary.name))
            if not result.success:
                self._publish_build_error("更新构建失败，已继续提供上一个版本", result)
                return False
            self._publish(self._network_status(message="资料已更新。", reminder=True))
            return True
        finally:
            self._build_lock.release()

    def configure_firewall(self) -> bool:
        """Configure LAN access only after the launcher receives an explicit click."""
        with self._configuration_lock:
            return self._configure_firewall_locked()

    def _configure_firewall_locked(self) -> bool:
        with self._lifecycle_lock:
            if not self._started or self._store is None or self._server is None:
                self._publish(ReaderStatus("error", "阅读器尚未运行，无法配置局域网访问。"))
                return False
            store = self._store
            old_server = self._server

        self._publish(ReaderStatus("configuring", "正在请求 Windows 配置专用网络访问……", self._current_url()))
        script_path = self.config_path.parent / "configure-firewall.ps1"
        try:
            configured = configure_firewall_rule(script_path, self.port, self.program_path)
            if not configured:
                self._publish(
                    ReaderStatus(
                        "local-only",
                        "防火墙配置未完成；阅读器仍只允许本机访问。",
                        self._local_url(),
                    )
                )
                return False
            with self._lifecycle_lock:
                if self._stop_requested:
                    return False
            status = self._inspect_network()
            if status.state != "running":
                self._publish(status)
                return False
            with self._lifecycle_lock:
                if self._stop_requested:
                    return False

            old_server.stop()
            replacement: ReadOnlyServer | None = None
            try:
                replacement = ReadOnlyServer(store, "0.0.0.0", self.port)
                replacement.start()
            except Exception as wildcard_error:
                if replacement is not None:
                    replacement.stop()
                fallback: ReadOnlyServer | None = None
                try:
                    fallback = ReadOnlyServer(store, "127.0.0.1", self.port)
                    fallback.start()
                except Exception as fallback_error:
                    if fallback is not None:
                        fallback.stop()
                    self._fail_closed_after_rebind(wildcard_error, fallback_error, old_server)
                    return False
                with self._lifecycle_lock:
                    self._server = fallback
                    self._lan_enabled = False
                self._publish(
                    ReaderStatus(
                        "error",
                        f"专用网络服务启动失败，已恢复本机预览：{wildcard_error}",
                        self._local_url(),
                    )
                )
                return False
            with self._lifecycle_lock:
                self._server = replacement
            self._publish(self._network_status(reminder=True))
            return True
        except Exception as error:
            self._publish(
                ReaderStatus(
                    "error",
                    f"防火墙配置未完成：{type(error).__name__}: {error}",
                    self._current_url(),
                )
            )
            return False

    def stop(self) -> None:
        """Stop watcher/server and delete only this session's temporary output."""
        with self._lifecycle_lock:
            if self._stop_requested:
                return
            self._stop_requested = True
            watcher = self._watcher

        if watcher is not None:
            watcher.stop()
        # A direct rebuild caller may not be the watcher thread. Wait until its
        # publication is complete before closing the store and temp directory.
        with self._configuration_lock:
            with self._build_lock:
                with self._lifecycle_lock:
                    server = self._server
                    store = self._store
                    temporary = self._temporary
                    self._watcher = None
                    self._server = None
                    self._store = None
                    self._temporary = None
                    self._started = False
                    self._lan_enabled = False
                    self._addresses = ()
                if server is not None:
                    server.stop()
                if store is not None:
                    store.close()
                if temporary is not None:
                    temporary.cleanup()

        with self._lifecycle_lock:
            if self._stopped_published:
                return
            self._stopped_published = True
        self._publish(ReaderStatus("stopped", "阅读器已停止。"))

    def _publish_network_status(self) -> ReaderStatus:
        """Inspect and publish current LAN eligibility without changing the OS."""
        status = self._inspect_network()
        self._publish(status)
        return status

    def _fail_closed_after_rebind(
        self,
        wildcard_error: Exception,
        fallback_error: Exception,
        stopped_server: ReadOnlyServer,
    ) -> None:
        """Clean the whole session when neither LAN nor loopback can rebind."""
        with self._lifecycle_lock:
            self._stop_requested = True
            watcher = self._watcher
        if watcher is not None:
            watcher.stop()
        with self._build_lock:
            with self._lifecycle_lock:
                server = self._server
                store = self._store
                temporary = self._temporary
                self._watcher = None
                self._server = None
                self._store = None
                self._temporary = None
                self._started = False
                self._lan_enabled = False
                self._addresses = ()
                self._network_reason = "服务重新绑定失败"
            if server is not None and server is not stopped_server:
                server.stop()
            if store is not None:
                store.close()
            if temporary is not None:
                temporary.cleanup()
        self._publish(
            ReaderStatus(
                "error",
                "专用网络和本机服务均无法重新启动，阅读器已停止："
                f"{wildcard_error}；{fallback_error}",
            )
        )

    def _next_build(self, store: SiteStore, temporary_root: Path) -> BuildResult:
        self._build_number += 1
        destination = temporary_root / f"site-{self._build_number:06d}"
        result = build_site(self.root, self.config_path, destination)
        if not result.success:
            return result
        try:
            store.activate(destination)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            log_path = temporary_root / f"{destination.name}.activation.log"
            log_path.write_text(message + "\n", encoding="utf-8")
            return BuildResult(
                False,
                error=message,
                log_path=log_path,
            )
        return result

    def _inspect_network(self) -> ReaderStatus:
        try:
            addresses = private_lan_addresses()
        except Exception as error:
            with self._lifecycle_lock:
                self._addresses = ()
                self._lan_enabled = False
                self._network_reason = f"无法读取专用网络状态：{error}"
            return self._network_status()

        address_text = tuple(address.address for address in addresses)
        if not address_text:
            with self._lifecycle_lock:
                self._addresses = ()
                self._lan_enabled = False
                self._network_reason = "未找到可用的 Windows 专用网络；请检查当前 Wi-Fi 的网络属性。"
            return self._network_status()

        try:
            rule_present = firewall_rule_present(self.port, self.program_path)
        except Exception as error:
            with self._lifecycle_lock:
                self._addresses = address_text
                self._lan_enabled = False
                self._network_reason = f"无法确认防火墙规则：{error}"
            return self._network_status()

        with self._lifecycle_lock:
            self._addresses = address_text
            self._lan_enabled = rule_present
            self._network_reason = (
                "" if rule_present else "尚未配置仅限专用网络的防火墙规则；当前只允许本机访问。"
            )
        return self._network_status()

    def _network_status(self, *, message: str | None = None, reminder: bool = False) -> ReaderStatus:
        with self._lifecycle_lock:
            lan_enabled = self._lan_enabled
            addresses = self._addresses
            reason = self._network_reason
        if lan_enabled and addresses:
            url = f"http://{addresses[0]}:{self.port}"
            text = message or "阅读器正在运行。"
            if reminder:
                text = f"{text} 请在同一 Wi-Fi 的 iPad Safari 打开下方地址。"
            return ReaderStatus("running", text, url)
        return ReaderStatus("local-only", reason or "当前只允许本机访问。", self._local_url())

    def _publish_build_error(self, prefix: str, result: BuildResult) -> None:
        detail = result.error or "未知构建错误"
        if result.log_path is not None:
            detail += f"；日志：{result.log_path}"
        self._publish(ReaderStatus("error", f"{prefix}：{detail}", self._current_url()))

    def _current_url(self) -> str | None:
        with self._lifecycle_lock:
            if self._lan_enabled and self._addresses:
                return f"http://{self._addresses[0]}:{self.port}"
            if self._started:
                return self._local_url()
        return None

    def _local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _validate_start_inputs(self) -> None:
        if self.program_path.name.casefold() != "pythonw.exe":
            raise ValueError("阅读器必须由桌面快捷方式指定的 pythonw.exe 启动")
        current_program = Path(sys.executable).resolve(strict=True)
        if current_program.name.casefold() != "pythonw.exe" or self.program_path != current_program:
            raise ValueError("阅读器程序必须与当前进程使用同一个 pythonw.exe")
        if not self.program_path.is_file():
            raise FileNotFoundError(f"找不到阅读器程序：{self.program_path}")
        if not self.root.is_dir():
            raise FileNotFoundError(f"找不到资料目录：{self.root}")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"找不到阅读器配置：{self.config_path}")

    def _publish(self, status: ReaderStatus) -> None:
        with self._lifecycle_lock:
            if self._stopped_published and status.state != "stopped":
                return
        try:
            self._on_status(status)
        except Exception:
            # A closing Tk window must not take down the server worker thread.
            pass
