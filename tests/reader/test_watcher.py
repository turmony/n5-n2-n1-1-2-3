import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from jlpt_notes.reader.watcher import ChangeDetector, FileStamp, SourceWatcher, snapshot_sources


class ReaderWatcherTests(unittest.TestCase):
    def test_snapshot_tracks_only_visible_md_and_jsonl_in_stable_order(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "folder").mkdir()
            (root / ".hidden").mkdir()
            (root / "b.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "a.md").write_text("a", encoding="utf-8")
            (root / "c.txt").write_text("c", encoding="utf-8")
            (root / ".ignored.md").write_text("hidden", encoding="utf-8")
            (root / ".hidden" / "ignored.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "folder" / "z.MD").write_text("z", encoding="utf-8")

            snapshot = snapshot_sources(root)

            self.assertEqual([item.path for item in snapshot], ["a.md", "b.jsonl", "folder/z.MD"])
            self.assertEqual(snapshot[0].size, 1)

    def test_detector_emits_once_after_changes_stabilize(self) -> None:
        detector = ChangeDetector(debounce_seconds=0.75)
        original = (FileStamp("a.md", 1, 1),)
        changed = (FileStamp("a.md", 2, 2),)

        self.assertFalse(detector.observe(original, 0.0))
        self.assertFalse(detector.observe(changed, 1.0))
        self.assertFalse(detector.observe(changed, 1.5))
        self.assertTrue(detector.observe(changed, 1.8))
        self.assertFalse(detector.observe(changed, 2.8))

    def test_detector_restarts_debounce_for_each_change_including_deletion(self) -> None:
        detector = ChangeDetector(debounce_seconds=1.0)
        original = (FileStamp("a.md", 1, 1), FileStamp("b.jsonl", 1, 1))
        modified = (FileStamp("a.md", 2, 2), FileStamp("b.jsonl", 1, 1))
        deleted = (FileStamp("a.md", 2, 2),)

        self.assertFalse(detector.observe(original, 0.0))
        self.assertFalse(detector.observe(modified, 2.0))
        self.assertFalse(detector.observe(deleted, 2.8))
        self.assertFalse(detector.observe(deleted, 3.7))
        self.assertTrue(detector.observe(deleted, 3.8))
        self.assertFalse(detector.observe(deleted, 4.8))

    def test_watcher_delivers_one_settled_batch_with_an_injectable_clock(self) -> None:
        original = (FileStamp("a.md", 1, 1),)
        renamed = (FileStamp("renamed.md", 1, 1),)
        snapshots = iter((original, renamed, renamed, renamed))
        notifications: list[str] = []
        watcher = SourceWatcher(
            Path("unused"),
            lambda: notifications.append("changed"),
            debounce_seconds=0.5,
            snapshotter=lambda root: next(snapshots),
        )

        self.assertFalse(watcher.poll_once(now=0.0))
        self.assertFalse(watcher.poll_once(now=1.0))
        self.assertFalse(watcher.poll_once(now=1.4))
        self.assertTrue(watcher.poll_once(now=1.5))

        self.assertEqual(notifications, ["changed"])

    def test_watcher_reports_callback_errors_and_keeps_polling(self) -> None:
        original = (FileStamp("a.md", 1, 1),)
        changed = (FileStamp("a.md", 2, 2),)
        snapshots = iter((original, changed, changed, changed))
        errors: list[str] = []
        watcher = SourceWatcher(
            Path("unused"),
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            debounce_seconds=0.0,
            on_error=errors.append,
            snapshotter=lambda root: next(snapshots),
        )

        self.assertFalse(watcher.poll_once(now=0.0))
        self.assertFalse(watcher.poll_once(now=1.0))
        self.assertFalse(watcher.poll_once(now=1.0))
        self.assertFalse(watcher.poll_once(now=2.0))

        self.assertEqual(len(errors), 1)
        self.assertIn("on_change callback failed: RuntimeError: boom", errors[0])

    def test_watcher_start_and_stop_use_a_daemon_polling_lifecycle(self) -> None:
        original = (FileStamp("a.md", 1, 1),)
        changed = (FileStamp("a.md", 2, 2),)
        baseline_seen = Event()
        callback_seen = Event()
        calls = 0

        def snapshotter(root: Path) -> tuple[FileStamp, ...]:
            nonlocal calls
            calls += 1
            if calls == 1:
                baseline_seen.set()
                return original
            return changed

        watcher = SourceWatcher(
            Path("unused"),
            callback_seen.set,
            interval_seconds=0.01,
            debounce_seconds=0.0,
            snapshotter=snapshotter,
        )
        watcher.start()
        self.assertTrue(baseline_seen.wait(timeout=1.0))
        self.assertTrue(callback_seen.wait(timeout=1.0))
        watcher.stop()

        self.assertFalse(watcher.is_running)


if __name__ == "__main__":
    unittest.main()
