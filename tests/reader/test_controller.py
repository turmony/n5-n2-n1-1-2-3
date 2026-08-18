import json
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread, current_thread
import unittest
from unittest.mock import patch

from jlpt_notes.reader.builder import BuildResult, SiteStore
from jlpt_notes.reader.controller import ReaderController, ReaderStatus
from jlpt_notes.reader.network import LanAddress, NetworkInspectionError


class _FakeStore:
    instances = []
    activation_error = None

    def __init__(self, session_root: Path) -> None:
        self.session_root = Path(session_root)
        self.activated = []
        self.close_calls = 0
        self.__class__.instances.append(self)

    def activate(self, site_dir: Path) -> None:
        if self.__class__.activation_error is not None:
            raise self.__class__.activation_error
        self.activated.append(Path(site_dir))

    def prepare(self, site_dir: Path) -> Path:
        return Path(site_dir)

    def discard(self, site_dir: Path) -> None:
        return

    @property
    def current(self) -> Path | None:
        return self.activated[-1] if self.activated else None

    def close(self) -> None:
        self.close_calls += 1


class _FakeServer:
    instances = []
    creation_errors = []

    def __init__(self, store, host: str, port: int) -> None:
        if self.__class__.creation_errors:
            raise self.__class__.creation_errors.pop(0)
        self.store = store
        self.host = host
        self.port = port
        self.start_calls = 0
        self.stop_calls = 0
        self.__class__.instances.append(self)

    @property
    def bound_port(self) -> int:
        return self.port

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeWatcher:
    instances = []

    def __init__(self, root: Path, on_change, **kwargs) -> None:
        self.root = Path(root)
        self.on_change = on_change
        self.on_error = kwargs.get("on_error")
        self.start_calls = 0
        self.stop_calls = 0
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _CleanupFailsOnceTemporary:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self._temporary = TemporaryDirectory(*args, **kwargs)
        self.name = self._temporary.name
        self.cleanup_calls = 0
        self.__class__.instances.append(self)

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        if self.cleanup_calls == 1:
            raise PermissionError("site file is still open")
        self._temporary.cleanup()


class ReaderControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeStore.instances.clear()
        _FakeStore.activation_error = None
        _FakeServer.instances.clear()
        _FakeServer.creation_errors.clear()
        _FakeWatcher.instances.clear()
        _CleanupFailsOnceTemporary.instances.clear()

    def test_no_private_network_stays_local_and_reports_reason(self) -> None:
        with TemporaryDirectory() as directory, \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            statuses = []
            program = Path(directory) / "pythonw.exe"
            program.write_bytes(b"test executable")
            controller = ReaderController(
                Path(directory), Path("reader/mkdocs.yml"), program, on_status=statuses.append
            )

            status = controller._publish_network_status()

            self.assertEqual(status.state, "local-only")
            self.assertEqual(statuses[-1], status)
            self.assertIn("专用网络", status.message)
            self.assertEqual(status.url, "http://127.0.0.1:8765")

    def test_start_builds_then_binds_lan_and_starts_watcher(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.private_lan_addresses",
                 return_value=(LanAddress(7, "192.168.1.42", "Private"),),
             ), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=True) as present:
            controller = ReaderController(root, config, program, on_status=statuses.append)

            self.assertTrue(controller.start())

            present.assert_called_with(8765, program.resolve())
            self.assertEqual(_FakeServer.instances[0].host, "0.0.0.0")
            self.assertEqual(_FakeServer.instances[0].start_calls, 1)
            self.assertEqual(_FakeWatcher.instances[0].start_calls, 1)
            self.assertEqual(len(_FakeStore.instances[0].activated), 1)
            self.assertEqual(statuses[-1].state, "running")
            self.assertEqual(statuses[-1].url, "http://192.168.1.42:8765")
            self.assertEqual(controller.urls, ("http://192.168.1.42:8765",))

            controller.stop()

    def test_edit_during_initial_build_is_rebuilt_from_the_prebuild_snapshot(self) -> None:
        from jlpt_notes.reader.watcher import SourceWatcher as RealSourceWatcher

        class DeterministicWatcher:
            def __init__(self, root: Path, on_change, **kwargs) -> None:
                self._watcher = RealSourceWatcher(
                    root,
                    on_change,
                    debounce_seconds=0.0,
                    initial_snapshot=kwargs.get("initial_snapshot"),
                )

            def start(self) -> None:
                self._watcher.poll_once(now=1.0)
                self._watcher.poll_once(now=1.0)

            def stop(self) -> None:
                self._watcher.stop()

        with self._runtime() as (root, config, program, statuses):
            source = root / "card.md"
            source.write_text("before build\n", encoding="utf-8")
            builds: list[str] = []

            def build(source_root, config_path, destination, *, previous_site=None):
                builds.append(source.read_text(encoding="utf-8"))
                if len(builds) == 1:
                    source.write_text("edited during build\n", encoding="utf-8")
                return BuildResult(True, version=f"v{len(builds)}")

            with patch("jlpt_notes.reader.controller.SiteStore", _FakeStore), \
                 patch("jlpt_notes.reader.controller.ReadOnlyServer", _FakeServer), \
                 patch("jlpt_notes.reader.controller.SourceWatcher", DeterministicWatcher), \
                 patch("jlpt_notes.reader.controller.build_site", side_effect=build), \
                 patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
                 patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
                controller = ReaderController(root, config, program, on_status=statuses.append)
                self.assertTrue(controller.start())

                self.assertEqual(builds, ["before build\n", "edited during build\n"])
                self.assertEqual(len(_FakeStore.instances[0].activated), 2)
                controller.stop()

    def test_rebuild_reuses_only_the_current_published_generation(self) -> None:
        previous_sites: list[Path | None] = []

        def build(source, config, destination, *, previous_site=None):
            previous_sites.append(previous_site)
            return BuildResult(True, version=f"v{len(previous_sites)}")

        with self._runtime() as (root, config, program, statuses), \
             patch("jlpt_notes.reader.controller.SiteStore", _FakeStore), \
             patch("jlpt_notes.reader.controller.ReadOnlyServer", _FakeServer), \
             patch("jlpt_notes.reader.controller.SourceWatcher", _FakeWatcher), \
             patch("jlpt_notes.reader.controller.build_site", side_effect=build), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)

            self.assertTrue(controller.start())
            current = _FakeStore.instances[0].current
            self.assertIsNotNone(current)
            self.assertTrue(controller.rebuild())

            self.assertEqual(previous_sites, [None, current])
            controller.stop()

    def test_missing_firewall_rule_binds_loopback_only(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.private_lan_addresses",
                 return_value=(LanAddress(7, "192.168.1.42", "Private"),),
             ), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False) as present:
            controller = ReaderController(root, config, program, on_status=statuses.append)

            self.assertTrue(controller.start())

            present.assert_called_with(8765, program.resolve())
            self.assertEqual(_FakeServer.instances[0].host, "127.0.0.1")
            self.assertEqual(statuses[-1].state, "local-only")
            self.assertIn("防火墙", statuses[-1].message)
            controller.stop()

    def test_initial_build_failure_never_starts_http_or_watcher(self) -> None:
        with self._runtime() as (root, config, program, statuses):
            log = root.parent / "initial-build.log"
            with self._patched_runtime(
                build_results=[BuildResult(False, error="broken markdown", log_path=log)]
            ):
                controller = ReaderController(root, config, program, on_status=statuses.append)

                self.assertFalse(controller.start())

            self.assertEqual(_FakeServer.instances, [])
            self.assertEqual(_FakeWatcher.instances, [])
            self.assertEqual(statuses[-1].state, "error")
            self.assertIn("broken markdown", statuses[-1].message)
            self.assertIn(str(log), statuses[-1].message)
            controller.stop()

    def test_start_uses_owned_session_cleanup_for_an_abandoned_reader_directory(self) -> None:
        from jlpt_notes.reader import controller as controller_module
        from jlpt_notes.reader.session import ReaderSessionDirectory

        self.assertTrue(
            hasattr(controller_module, "ReaderSessionDirectory"),
            "controller still creates an unowned TemporaryDirectory",
        )
        with self._runtime() as (root, config, program, statuses), \
             TemporaryDirectory() as session_parent:
            parent = Path(session_parent)
            abandoned = parent / "jlpt-reader-abandoned"
            abandoned.mkdir()
            (abandoned / "owner.lock").write_bytes(b"\0")
            with patch("jlpt_notes.reader.controller.SiteStore", _FakeStore), \
                 patch("jlpt_notes.reader.controller.ReadOnlyServer", _FakeServer), \
                 patch("jlpt_notes.reader.controller.SourceWatcher", _FakeWatcher), \
                 patch(
                     "jlpt_notes.reader.controller.ReaderSessionDirectory",
                     side_effect=lambda: ReaderSessionDirectory(parent=parent),
                 ), \
                 patch(
                     "jlpt_notes.reader.controller.build_site",
                     return_value=BuildResult(True, version="v1"),
                 ), \
                 patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
                 patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
                controller = ReaderController(root, config, program, on_status=statuses.append)
                self.assertTrue(controller.start())

                self.assertFalse(abandoned.exists())
                controller.stop()

    def test_activation_failure_gets_a_temporary_log_and_never_starts_http(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]):
            _FakeStore.activation_error = RuntimeError("publication blocked")
            controller = ReaderController(root, config, program, on_status=statuses.append)

            self.assertFalse(controller.start())

            self.assertEqual(_FakeServer.instances, [])
            self.assertEqual(statuses[-1].state, "error")
            self.assertIn("publication blocked", statuses[-1].message)
            log_text = statuses[-1].message.split("日志：", 1)[1]
            log_path = Path(log_text)
            self.assertTrue(log_path.is_file())
            self.assertIn("publication blocked", log_path.read_text(encoding="utf-8"))
            controller.stop()

    def test_close_waits_for_initial_build_before_cleaning_session(self) -> None:
        build_entered = Event()
        build_release = Event()

        def build(source, config, destination):
            build_entered.set()
            build_release.wait(2)
            return BuildResult(True, version="v1")

        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_side_effect=build), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            start_worker = Thread(target=controller.start)
            start_worker.start()
            self.assertTrue(build_entered.wait(1))
            stop_worker = Thread(target=controller.stop)
            stop_worker.start()

            stop_worker.join(0.1)
            self.assertTrue(stop_worker.is_alive())
            self.assertEqual(_FakeStore.instances[0].close_calls, 0)

            build_release.set()
            start_worker.join(2)
            stop_worker.join(2)
            self.assertFalse(start_worker.is_alive())
            self.assertFalse(stop_worker.is_alive())
            self.assertEqual(_FakeServer.instances, [])
            self.assertEqual(_FakeStore.instances[0].close_calls, 1)
            self.assertEqual(statuses[-1].state, "stopped")

    def test_stop_before_temporary_publication_cleans_late_created_session(self) -> None:
        creation_entered = Event()
        creation_release = Event()
        created_temporaries = []

        def delayed_temporary(*args, **kwargs):
            creation_entered.set()
            creation_release.wait(2)
            temporary = TemporaryDirectory(*args, **kwargs)
            created_temporaries.append(temporary)
            return temporary

        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch("jlpt_notes.reader.controller.ReaderSessionDirectory", side_effect=delayed_temporary), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            start_worker = Thread(target=controller.start)
            start_worker.start()
            self.assertTrue(creation_entered.wait(1))
            stop_worker = Thread(target=controller.stop)
            stop_worker.start()

            creation_release.set()
            start_worker.join(2)
            stop_worker.join(2)
            controller.stop()

            self.assertFalse(start_worker.is_alive())
            self.assertFalse(stop_worker.is_alive())
            self.assertEqual(len(created_temporaries), 1)
            self.assertFalse(Path(created_temporaries[0].name).exists())
            self.assertIsNone(controller._temporary)
            self.assertIsNone(controller._store)
            self.assertIsNone(controller._server)
            self.assertIsNone(controller._watcher)
            self.assertEqual(_FakeServer.instances, [])
            self.assertEqual(statuses[-1].state, "stopped")

    def test_completed_early_stop_cannot_be_overwritten_by_delayed_start_status(self) -> None:
        preparing_entered = Event()
        preparing_release = Event()
        with self._runtime() as (root, config, program, statuses):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            original_publish = controller._publish

            def delayed_publish(status):
                if status.state == "preparing":
                    preparing_entered.set()
                    preparing_release.wait(2)
                original_publish(status)

            with patch.object(controller, "_publish", side_effect=delayed_publish):
                start_worker = Thread(target=controller.start)
                start_worker.start()
                self.assertTrue(preparing_entered.wait(1))
                controller.stop()
                preparing_release.set()
                start_worker.join(2)

            self.assertFalse(start_worker.is_alive())
            self.assertEqual([status.state for status in statuses], ["stopped"])

    def test_rebuild_failure_keeps_last_good_and_reports_temporary_log(self) -> None:
        with self._runtime() as (root, config, program, statuses):
            log = root.parent / "site-000002.log"
            with self._patched_runtime(
                build_results=[
                    BuildResult(True, version="v1"),
                    BuildResult(False, error="bad update", log_path=log),
                ]
            ), patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
                 patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
                controller = ReaderController(root, config, program, on_status=statuses.append)
                self.assertTrue(controller.start())
                original = tuple(_FakeStore.instances[0].activated)

                self.assertFalse(controller.rebuild())

                self.assertEqual(tuple(_FakeStore.instances[0].activated), original)
                self.assertEqual(statuses[-1].state, "error")
                self.assertIn(str(log), statuses[-1].message)
                controller.stop()

    def test_repeated_rejected_candidates_are_bounded_and_last_good_stays_readable(self) -> None:
        class RejectingStore(SiteStore):
            def __init__(self, session_root: Path) -> None:
                super().__init__(session_root)
                self.reject_publication = False

            def activate(self, site_dir: Path) -> None:
                if self.reject_publication:
                    raise RuntimeError("publication refused")
                super().activate(site_dir)

        with self._runtime() as (root, config, program, statuses), \
             TemporaryDirectory() as session_parent:
            from jlpt_notes.reader.session import ReaderSessionDirectory

            builds: list[Path] = []

            def build(source, config_path, destination, *, previous_site=None):
                destination.mkdir()
                (destination / "index.html").write_text(
                    f"build-{len(builds) + 1}", encoding="utf-8"
                )
                builds.append(destination)
                return BuildResult(True, version=f"v{len(builds)}")

            with patch("jlpt_notes.reader.controller.SiteStore", RejectingStore), \
                 patch("jlpt_notes.reader.controller.ReadOnlyServer", _FakeServer), \
                 patch("jlpt_notes.reader.controller.SourceWatcher", _FakeWatcher), \
                 patch(
                     "jlpt_notes.reader.controller.ReaderSessionDirectory",
                     side_effect=lambda: ReaderSessionDirectory(parent=Path(session_parent)),
                 ), \
                 patch("jlpt_notes.reader.controller.build_site", side_effect=build), \
                 patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
                 patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
                controller = ReaderController(root, config, program, on_status=statuses.append)
                self.assertTrue(controller.start())
                store = controller._store
                assert isinstance(store, RejectingStore)
                last_good = store.current
                assert last_good is not None
                store.reject_publication = True

                with patch(
                    "jlpt_notes.reader.builder.shutil.rmtree",
                    side_effect=PermissionError("persistent cleanup failure"),
                ):
                    for _ in range(5):
                        self.assertFalse(controller.rebuild())

                actual_build_count = len(builds)
                actual_current = store.current
                active = store.resolve("index.html")
                assert active is not None
                active_text = active.read_text(encoding="utf-8")
                session_dirs = [
                    path for path in Path(controller._temporary.name).iterdir() if path.is_dir()
                ]
                cleanup_error_count = len(store.cleanup_errors)
                controller.stop()

                self.assertEqual(actual_build_count, 3)
                self.assertEqual(actual_current, last_good)
                self.assertEqual(active_text, "build-1")
                self.assertEqual(len(session_dirs), 3)
                self.assertEqual(cleanup_error_count, 2)

    def test_rebuild_coalesces_while_an_existing_rebuild_is_busy(self) -> None:
        entered = Event()
        release = Event()

        def build(source, config, destination):
            build.calls += 1
            if build.calls == 2:
                entered.set()
                release.wait(2)
            return BuildResult(True, version=f"v{build.calls}")

        build.calls = 0
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_side_effect=build), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())
            worker = Thread(target=controller.rebuild)
            worker.start()
            self.assertTrue(entered.wait(1))

            self.assertFalse(controller.rebuild())

            release.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(build.calls, 2)
            controller.stop()

    def test_configure_firewall_uses_same_pythonw_for_config_and_status_then_rebinds(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.private_lan_addresses",
                 return_value=(LanAddress(7, "192.168.1.42", "Private"),),
             ), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", side_effect=[False, True]) as present, \
             patch("jlpt_notes.reader.controller.configure_firewall_rule", return_value=True) as configure:
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())
            self.assertEqual(_FakeServer.instances[0].host, "127.0.0.1")

            self.assertTrue(controller.configure_firewall())

            configure.assert_called_once_with(
                config.parent / "configure-firewall.ps1", 8765, program.resolve()
            )
            self.assertEqual(
                present.call_args_list[-1].args,
                (8765, program.resolve()),
            )
            self.assertEqual(_FakeServer.instances[0].stop_calls, 1)
            self.assertEqual(_FakeServer.instances[1].host, "0.0.0.0")
            self.assertEqual(statuses[-1].state, "running")
            controller.stop()

    def test_double_rebind_failure_fails_closed_without_advertising_lan(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.private_lan_addresses",
                 return_value=(LanAddress(7, "192.168.1.42", "Private"),),
             ), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", side_effect=[False, True]), \
             patch("jlpt_notes.reader.controller.configure_firewall_rule", return_value=True):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())
            session_path = Path(controller._temporary.name)
            _FakeServer.creation_errors.extend(
                [OSError("wildcard bind failed"), OSError("loopback bind failed")]
            )

            self.assertFalse(controller.configure_firewall())

            self.assertEqual(len(_FakeServer.instances), 1)
            self.assertEqual(_FakeServer.instances[0].stop_calls, 1)
            self.assertEqual(_FakeWatcher.instances[0].stop_calls, 1)
            self.assertEqual(_FakeStore.instances[0].close_calls, 1)
            self.assertFalse(session_path.exists())
            self.assertEqual(controller.urls, ())
            self.assertIsNone(controller._server)
            self.assertIsNone(controller._store)
            self.assertIsNone(controller._temporary)
            self.assertEqual(statuses[-1].state, "error")
            self.assertIsNone(statuses[-1].url)
            self.assertIn("已停止", statuses[-1].message)
            controller.stop()

    def test_close_during_firewall_confirmation_cannot_leave_a_server_running(self) -> None:
        configuration_started = Event()
        configuration_release = Event()

        def configure(*args):
            configuration_started.set()
            configuration_release.wait(2)
            return True

        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.private_lan_addresses",
                 return_value=(LanAddress(7, "192.168.1.42", "Private"),),
             ), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", side_effect=[False, True]), \
             patch("jlpt_notes.reader.controller.configure_firewall_rule", side_effect=configure):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())
            configure_worker = Thread(target=controller.configure_firewall)
            configure_worker.start()
            self.assertTrue(configuration_started.wait(1))

            stop_worker = Thread(target=controller.stop)
            stop_worker.start()
            configuration_release.set()
            configure_worker.join(2)
            stop_worker.join(2)

            self.assertFalse(configure_worker.is_alive())
            self.assertFalse(stop_worker.is_alive())
            self.assertEqual(len(_FakeServer.instances), 1)
            self.assertEqual(_FakeServer.instances[0].stop_calls, 1)
            self.assertEqual(statuses[-1].state, "stopped")

    def test_start_rejects_non_pythonw_and_invalid_inputs_before_build(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "jlpt_notes.reader.controller.build_site"
        ) as build:
            base = Path(directory)
            root = base / "notes"
            root.mkdir()
            config = base / "mkdocs.yml"
            config.write_text("site_name: test\n", encoding="utf-8")
            python = base / "python.exe"
            python.write_bytes(b"test")

            with self.assertRaisesRegex(ValueError, "pythonw.exe"):
                ReaderController(root, config, python).start()
            with self.assertRaisesRegex(ValueError, "1024.*65535"):
                ReaderController(root, config, python.with_name("pythonw.exe"), port=80)

            build.assert_not_called()

    def test_controller_rejects_a_different_existing_pythonw_than_current_process(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "jlpt_notes.reader.controller.build_site"
        ) as build:
            base = Path(directory)
            root = base / "notes"
            root.mkdir()
            config = base / "mkdocs.yml"
            config.write_text("site_name: test\n", encoding="utf-8")
            current = base / "current" / "pythonw.exe"
            supplied = base / "other" / "pythonw.exe"
            current.parent.mkdir()
            supplied.parent.mkdir()
            current.write_bytes(b"current process")
            supplied.write_bytes(b"other process")

            with patch.object(sys, "executable", str(current)):
                controller = ReaderController(root, config, supplied)
                with self.assertRaisesRegex(ValueError, "当前.*pythonw.exe"):
                    controller.start()

            build.assert_not_called()

    def test_launcher_rejects_an_unrelated_pythonw_without_opening_tk(self) -> None:
        from jlpt_notes.reader.launcher import run

        with TemporaryDirectory() as directory, patch(
            "jlpt_notes.reader.launcher.tk.Tk"
        ) as create_window:
            program = Path(directory) / "pythonw.exe"
            program.write_bytes(b"unrelated executable")

            with self.assertRaisesRegex(ValueError, "同一个 pythonw.exe"):
                run(Path("notes"), Path("reader/mkdocs.yml"), program)

            create_window.assert_not_called()

    def test_launcher_status_pump_never_calls_tk_from_worker_and_closes_safely(self) -> None:
        from jlpt_notes.reader.launcher import _StatusPump

        class FakeWindow:
            def __init__(self) -> None:
                self.ui_thread = current_thread()
                self.after_calls = []
                self.cross_thread_after = Event()

            def after(self, delay, callback):
                if current_thread() is not self.ui_thread:
                    self.cross_thread_after.set()
                self.after_calls.append((delay, callback))

        window = FakeWindow()
        applied = []
        pump = _StatusPump(window, applied.append, interval_ms=25)
        pump.start()
        self.assertEqual(len(window.after_calls), 1)

        controller_lock = Lock()
        worker_holds_lock = Event()
        statuses_posted = Event()
        release_worker = Event()
        first = ReaderStatus("building", "building")
        second = ReaderStatus("running", "running", "http://192.168.1.42:8765")

        def worker_publish() -> None:
            with controller_lock:
                worker_holds_lock.set()
                pump.post(first)
                pump.post(second)
                statuses_posted.set()
                release_worker.wait(2)

        worker = Thread(target=worker_publish)
        worker.start()
        self.assertTrue(worker_holds_lock.wait(1))
        self.assertTrue(statuses_posted.wait(1))
        self.assertFalse(window.cross_thread_after.is_set())

        pump.close()
        release_worker.set()
        self.assertTrue(controller_lock.acquire(timeout=1))
        controller_lock.release()
        worker.join(1)
        self.assertFalse(worker.is_alive())

        # A callback already queued by the UI loop becomes a harmless no-op.
        window.after_calls[0][1]()
        self.assertEqual(applied, [])
        self.assertEqual(len(window.after_calls), 1)
        pump.post(ReaderStatus("error", "late"))
        self.assertEqual(applied, [])

    def test_launcher_status_pump_drains_in_order_and_reschedules_only_on_ui(self) -> None:
        from jlpt_notes.reader.launcher import _StatusPump

        class FakeWindow:
            def __init__(self) -> None:
                self.ui_thread = current_thread()
                self.after_calls = []

            def after(self, delay, callback):
                self.assert_ui_thread()
                self.after_calls.append((delay, callback))

            def assert_ui_thread(self) -> None:
                if current_thread() is not self.ui_thread:
                    raise AssertionError("Tk after called outside UI thread")

        window = FakeWindow()
        applied = []
        pump = _StatusPump(window, applied.append, interval_ms=25)
        pump.start()
        statuses = [
            ReaderStatus("building", "one"),
            ReaderStatus("updating", "two"),
            ReaderStatus("running", "three", "http://192.168.1.42:8765"),
        ]
        for status in statuses:
            pump.post(status)

        window.after_calls.pop(0)[1]()

        self.assertEqual(applied, statuses)
        self.assertEqual(len(window.after_calls), 1)
        self.assertEqual(window.after_calls[0][0], 25)

    def test_launcher_destroys_the_window_even_when_stop_cleanup_raises(self) -> None:
        from jlpt_notes.reader import launcher

        self.assertTrue(
            hasattr(launcher, "_stop_and_destroy"),
            "launcher close needs an exception-safe cleanup boundary",
        )
        stop_and_destroy = getattr(launcher, "_stop_and_destroy")

        class FailingController:
            def stop(self) -> None:
                raise PermissionError("locked session")

        class FakeWindow:
            def __init__(self) -> None:
                self.destroy_calls = 0

            def destroy(self) -> None:
                self.destroy_calls += 1

        window = FakeWindow()
        with self.assertRaisesRegex(PermissionError, "locked session"):
            stop_and_destroy(FailingController(), window)

        self.assertEqual(window.destroy_calls, 1)

    def test_stop_is_idempotent_and_stops_watcher_server_store(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())

            controller.stop()
            controller.stop()

            self.assertEqual(_FakeWatcher.instances[0].stop_calls, 1)
            self.assertEqual(_FakeServer.instances[0].stop_calls, 1)
            self.assertEqual(_FakeStore.instances[0].close_calls, 1)
            self.assertEqual([status.state for status in statuses].count("stopped"), 1)

    def test_stop_retries_only_the_temporary_cleanup_that_failed(self) -> None:
        with self._runtime() as (root, config, program, statuses), \
             self._patched_runtime(build_results=[BuildResult(True, version="v1")]), \
             patch(
                 "jlpt_notes.reader.controller.ReaderSessionDirectory",
                 _CleanupFailsOnceTemporary,
             ), \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            controller = ReaderController(root, config, program, on_status=statuses.append)
            self.assertTrue(controller.start())
            session = _CleanupFailsOnceTemporary.instances[0]

            with self.assertRaisesRegex(PermissionError, "still open"):
                controller.stop()

            self.assertIs(controller._temporary, session)
            self.assertTrue(Path(session.name).is_dir())
            self.assertEqual([status.state for status in statuses].count("stopped"), 0)

            controller.stop()
            controller.stop()

            self.assertEqual(session.cleanup_calls, 2)
            self.assertFalse(Path(session.name).exists())
            self.assertEqual(_FakeWatcher.instances[0].stop_calls, 1)
            self.assertEqual(_FakeServer.instances[0].stop_calls, 1)
            self.assertEqual(_FakeStore.instances[0].close_calls, 1)
            self.assertEqual([status.state for status in statuses].count("stopped"), 1)

    def test_shortcut_whatif_reports_exact_pythonw_contract_without_creating_link(self) -> None:
        project = Path(__file__).resolve().parents[2]
        script = project / "reader" / "install-shortcut.ps1"
        with TemporaryDirectory() as directory:
            temporary = Path(directory)
            program = temporary / "runtime with spaces" / "pythonw.exe"
            program.parent.mkdir()
            program.write_bytes(b"test executable")
            desktop = temporary / "desktop"
            desktop.mkdir()
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Pythonw",
                    str(program),
                    "-DesktopPath",
                    str(desktop),
                    "-WhatIf",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                check=True,
            )

            preview = json.loads(completed.stdout)
            self.assertTrue(Path(preview["TargetPath"]).samefile(program))
            self.assertEqual(preview["WorkingDirectory"], str(project.resolve()))
            self.assertEqual(preview["Description"], "手动启动 JLPT iPad 局域网只读阅读器")
            self.assertIn('--root "', preview["Arguments"])
            self.assertIn('--config "', preview["Arguments"])
            self.assertFalse((desktop / "JLPT iPad 阅读器.lnk").exists())

    @contextmanager
    def _runtime(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "notes"
            root.mkdir()
            config = base / "reader" / "mkdocs.yml"
            config.parent.mkdir()
            config.write_text("site_name: test\n", encoding="utf-8")
            (config.parent / "configure-firewall.ps1").write_text("# test\n", encoding="utf-8")
            program = base / "runtime" / "pythonw.exe"
            program.parent.mkdir()
            program.write_bytes(b"test executable")
            statuses = []
            with patch.object(sys, "executable", str(program)):
                yield root, config.resolve(), program, statuses

    @contextmanager
    def _patched_runtime(self, *, build_results=None, build_side_effect=None):
        results = iter(build_results or ())

        def fake_build(source, config, destination, *, previous_site=None):
            if build_side_effect is not None:
                return build_side_effect(source, config, destination)
            return next(results)

        with patch("jlpt_notes.reader.controller.SiteStore", _FakeStore), \
             patch("jlpt_notes.reader.controller.ReadOnlyServer", _FakeServer), \
             patch("jlpt_notes.reader.controller.SourceWatcher", _FakeWatcher), \
             patch("jlpt_notes.reader.controller.build_site", side_effect=fake_build):
            yield


if __name__ == "__main__":
    unittest.main()
