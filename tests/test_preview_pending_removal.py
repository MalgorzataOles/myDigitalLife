#!/usr/bin/env python3
import os
import sys
import shutil
import unittest
import tempfile
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts.preview_pending_removal import main


class TestPreviewPendingRemoval(unittest.TestCase):
    """
    Test suite for preview_pending_removal.py: a non-destructive, re-runnable
    helper that shows which Original/ files didn't make it into Sorted/.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.session_path = os.path.join(self.test_dir, "Workspace", "Gosia_2026-09-25")
        self.original_path = os.path.join(self.session_path, "Original")
        self.sorted_path = os.path.join(self.session_path, "Sorted")
        os.makedirs(self.original_path, exist_ok=True)
        os.makedirs(self.sorted_path, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def test_halts_when_original_missing(self):
        shutil.rmtree(self.original_path)
        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

    def test_halts_when_sorted_missing(self):
        shutil.rmtree(self.sorted_path)
        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

    def test_flags_files_present_in_original_but_absent_from_sorted(self):
        self._write(os.path.join(self.original_path, "kept.jpg"), b"kept content")
        self._write(os.path.join(self.sorted_path, "Family", "kept.jpg"), b"kept content")
        self._write(os.path.join(self.original_path, "dropped.jpg"), b"dropped content")

        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            main()

        preview_path = os.path.join(self.session_path, "ToBeDeleted")
        self.assertTrue(os.path.exists(os.path.join(preview_path, "dropped.jpg")))
        self.assertFalse(os.path.exists(os.path.join(preview_path, "kept.jpg")))

    def test_each_duplicate_original_copy_is_flagged_individually(self):
        # Two different Original files share content, neither made it into Sorted.
        self._write(os.path.join(self.original_path, "a", "photo.jpg"), b"same_bytes")
        self._write(os.path.join(self.original_path, "b", "photo_copy.jpg"), b"same_bytes")

        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            main()

        preview_path = os.path.join(self.session_path, "ToBeDeleted")
        self.assertTrue(os.path.exists(os.path.join(preview_path, "a", "photo.jpg")))
        self.assertTrue(os.path.exists(os.path.join(preview_path, "b", "photo_copy.jpg")))

    def test_rerun_removes_stale_entries_once_file_is_rescued(self):
        self._write(os.path.join(self.original_path, "maybe.jpg"), b"maybe content")

        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            main()

        preview_path = os.path.join(self.session_path, "ToBeDeleted")
        self.assertTrue(os.path.exists(os.path.join(preview_path, "maybe.jpg")))

        # User changes their mind and rescues the file into Sorted/.
        self._write(os.path.join(self.sorted_path, "maybe.jpg"), b"maybe content")

        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            main()

        self.assertFalse(os.path.exists(os.path.join(preview_path, "maybe.jpg")))

    def test_no_preview_folder_created_when_nothing_pending(self):
        self._write(os.path.join(self.original_path, "kept.jpg"), b"kept content")
        self._write(os.path.join(self.sorted_path, "kept.jpg"), b"kept content")

        with patch.object(sys, "argv", ["preview_pending_removal.py", self.session_path]):
            main()

        preview_path = os.path.join(self.session_path, "ToBeDeleted")
        self.assertFalse(os.path.exists(preview_path))


if __name__ == "__main__":
    unittest.main()
