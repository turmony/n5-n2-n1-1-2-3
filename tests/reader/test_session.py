import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class ReaderSessionTests(unittest.TestCase):
    def _session_module(self):
        spec = importlib.util.find_spec("jlpt_notes.reader.session")
        self.assertIsNotNone(spec, "reader session ownership support is missing")
        return importlib.import_module("jlpt_notes.reader.session")

    def test_next_session_removes_abandoned_session_but_preserves_active_owner(self) -> None:
        session_module = self._session_module()
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            active = session_module.ReaderSessionDirectory(parent=parent)
            code = (
                "from pathlib import Path; "
                "from jlpt_notes.reader.session import ReaderSessionDirectory; "
                f"session=ReaderSessionDirectory(parent=Path({str(parent)!r})); "
                "print(session.name)"
            )
            completed = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                check=True,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
            )
            abandoned = Path(completed.stdout.strip())
            self.assertTrue(abandoned.is_dir())

            replacement = session_module.ReaderSessionDirectory(parent=parent)
            try:
                self.assertTrue(Path(active.name).is_dir())
                self.assertTrue(Path(replacement.name).is_dir())
                self.assertFalse(abandoned.exists())
            finally:
                replacement.cleanup()
                active.cleanup()

    def test_cleanup_skips_unowned_or_unresolved_candidates(self) -> None:
        session_module = self._session_module()
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside_directory:
            parent = Path(directory)
            unowned = parent / "jlpt-reader-no-owner"
            unowned.mkdir()
            outside = Path(outside_directory)
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            linked = parent / "jlpt-reader-linked"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError:
                linked = None

            errors = session_module.cleanup_stale_reader_sessions(parent)

            self.assertEqual(errors, ())
            self.assertTrue(unowned.is_dir())
            self.assertTrue((outside / "keep.txt").is_file())
            if linked is not None:
                self.assertTrue(linked.exists())

    def test_cleanup_error_reporting_is_bounded(self) -> None:
        session_module = self._session_module()
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            for number in range(20):
                candidate = parent / f"jlpt-reader-abandoned-{number:02d}"
                candidate.mkdir()
                (candidate / "owner.lock").write_bytes(b"\0")

            with patch(
                "jlpt_notes.reader.session.shutil.rmtree",
                side_effect=PermissionError("locked stale session"),
            ):
                errors = session_module.cleanup_stale_reader_sessions(parent)

            self.assertEqual(len(errors), 8)
            self.assertTrue(all("PermissionError" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
