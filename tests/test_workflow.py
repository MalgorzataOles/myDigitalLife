#!/usr/bin/env python3
import io
import os
import sys
import shutil
import unittest
import tempfile
import unicodedata
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts import register_and_exclude, preview_pending_removal, finalize_curation
from scripts.common import (
    read_checksum_pairs,
    read_checksum_rows,
    append_checksum_lines,
    find_unregistered_files,
    check_folder_layout,
)


class WorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dropzone = os.path.join(self.test_dir, "Dropzone")
        self.excluded = os.path.join(self.test_dir, "Excluded")
        self.session = os.path.join(self.test_dir, "Workspace", "Gosia_20260925")
        os.makedirs(self.dropzone)
        os.makedirs(os.path.join(self.session, "Original"))
        os.makedirs(os.path.join(self.session, "Sorted"))
        self.config = {"dropzone_path": self.dropzone, "excluded_path": self.excluded}
        self.registry = os.path.join(self.dropzone, "registered.sha256")
        self.ledger = os.path.join(self.dropzone, "exclude.sha256")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def run_script(self, module, *args):
        """Runs a script's main() with the test config and returns what it printed."""
        output = io.StringIO()
        with patch.object(module, "load_configuration", return_value=self.config, create=True):
            with patch.object(sys, "argv", [module.__name__, *args]):
                with redirect_stdout(output):
                    module.main()
        return output.getvalue()

    def register(self):
        return self.run_script(register_and_exclude)

    def finalize(self, *flags):
        return self.run_script(finalize_curation, self.session, *flags)


class TestFullWorkflow(WorkflowTestCase):
    def test_complete_workflow_from_dump_to_archive_and_redump(self):
        # 1. A backup is dumped and registered.
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"photo a")
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "b.jpg"), b"photo b")
        self.register()
        self.assertEqual(len(read_checksum_rows(self.registry)), 2)

        # 2./3. The batch is copied into Original and Sorted; b.jpg is dropped from Sorted.
        for name in ("a.jpg", "b.jpg"):
            self.write(os.path.join(self.session, "Original", name), b"photo " + name[0].encode())
        self.write(os.path.join(self.session, "Sorted", "Holiday", "a.jpg"), b"photo a")

        # 4. Preview shows b.jpg and changes nothing in Dropzone.
        preview_pending_removal_args = [self.session]
        with patch.object(sys, "argv", ["preview", *preview_pending_removal_args]):
            with redirect_stdout(io.StringIO()):
                preview_pending_removal.main()
        self.assertTrue(os.path.exists(os.path.join(self.session, "ToBeDeleted", "b.jpg")))

        # 5. A dry run changes nothing.
        self.finalize("--dry-run")
        self.assertEqual(len(read_checksum_rows(self.registry)), 2)
        self.assertTrue(os.path.exists(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg")))

        # 6. The real run archives both files and records both hashes.
        self.finalize("--commit")
        self.assertEqual(len(read_checksum_rows(self.registry)), 0)
        self.assertEqual(len(read_checksum_pairs(self.ledger)), 2)
        self.assertFalse(os.path.exists(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg")))

        # 7. Running it again is harmless.
        self.finalize("--commit")
        self.assertEqual(len(read_checksum_pairs(self.ledger)), 2)

        # 8. The same photo dumped again is caught on intake, a new one is registered.
        self.write(os.path.join(self.dropzone, "Phone2", "20260930", "again.jpg"), b"photo a")
        self.write(os.path.join(self.dropzone, "Phone2", "20260930", "new.jpg"), b"brand new")
        self.register()
        self.assertFalse(os.path.exists(os.path.join(self.dropzone, "Phone2", "20260930", "again.jpg")))
        self.assertEqual([row[1] for row in read_checksum_rows(self.registry)],
                         [os.path.join("Phone2", "20260930", "new.jpg")])


class TestRegisterRobustness(WorkflowTestCase):
    def test_excluded_folder_inside_dropzone_is_refused(self):
        self.config["excluded_path"] = os.path.join(self.dropzone, "Excluded")
        with self.assertRaises(SystemExit) as cm:
            self.register()
        self.assertEqual(cm.exception.code, 1)

    def test_names_with_tabs_are_reported_and_not_registered(self):
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "bad\tname.jpg"), b"x")
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "good.jpg"), b"y")
        output = self.register()
        self.assertIn("name contains a tab or line break", output)
        self.assertEqual([os.path.basename(r[1]) for r in read_checksum_rows(self.registry)], ["good.jpg"])

    def test_windows_metadata_files_are_ignored(self):
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "Thumbs.db"), b"x")
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "desktop.ini"), b"x")
        self.register()
        self.assertFalse(os.path.exists(self.registry))

    def test_interrupted_registry_write_leaves_registry_intact_and_rerun_works(self):
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "b.jpg"), b"b")

        with patch("scripts.common.os.replace", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.register()
        self.assertEqual(len(read_checksum_rows(self.registry)), 1)

        self.register()
        self.assertEqual(len(read_checksum_rows(self.registry)), 2)

    def test_registry_with_a_cut_off_row_from_an_older_run_still_registers_the_real_file(self):
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")
        with open(self.registry, "w", encoding="utf-8") as f:
            f.write("abc123\tPhone1/20260920/a.j")  # cut off mid-row, no newline
        self.register()
        registered = [row[1] for row in read_checksum_rows(self.registry)]
        self.assertIn(os.path.join("Phone1", "20260920", "a.jpg"), registered)

    def test_accented_names_match_whichever_unicode_form_is_stored(self):
        composed = unicodedata.normalize("NFC", "Müller.jpg")
        decomposed = unicodedata.normalize("NFD", "Müller.jpg")
        self.write(os.path.join(self.dropzone, "Phone1", decomposed), b"x")
        self.assertEqual(find_unregistered_files(self.dropzone, {os.path.join("Phone1", composed)}), [])


class TestLedgerAppend(WorkflowTestCase):
    def test_append_after_a_cut_off_line_starts_on_a_new_line(self):
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write("deadbeef")  # no trailing newline
        append_checksum_lines(self.ledger, ["cafe\tpath.jpg"])
        with open(self.ledger, encoding="utf-8") as f:
            self.assertEqual(f.read(), "deadbeef\ncafe\tpath.jpg\n")


class TestFinalizeRobustness(WorkflowTestCase):
    def _register_one_handled_file(self):
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")

    def test_unreadable_file_in_sorted_aborts_without_changes(self):
        self._register_one_handled_file()
        locked = os.path.join(self.session, "Sorted", "locked.jpg")
        self.write(locked, b"locked")
        os.chmod(locked, 0o000)
        try:
            with self.assertRaises(SystemExit) as cm:
                self.finalize("--commit")
        finally:
            os.chmod(locked, 0o644)
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(len(read_checksum_rows(self.registry)), 1)
        self.assertFalse(os.path.exists(self.ledger))

    def test_session_folder_inside_dropzone_is_refused(self):
        self._register_one_handled_file()
        self.session = os.path.join(self.dropzone, "Workspace", "Gosia_20260925")
        os.makedirs(os.path.join(self.session, "Original"))
        os.makedirs(os.path.join(self.session, "Sorted"))
        with self.assertRaises(SystemExit) as cm:
            self.finalize("--commit")
        self.assertEqual(cm.exception.code, 1)

    def test_failed_move_stops_cleanly_and_rerun_completes(self):
        self._register_one_handled_file()
        with patch("scripts.finalize_curation.shutil.move", side_effect=OSError("network share went away")):
            with self.assertRaises(SystemExit) as cm:
                self.finalize("--commit")
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(len(read_checksum_rows(self.registry)), 1)

        self.finalize("--commit")
        self.assertEqual(len(read_checksum_rows(self.registry)), 0)
        self.assertEqual(len(read_checksum_pairs(self.ledger)), 1)


class TestFolderLayout(unittest.TestCase):
    def test_overlapping_folders_are_detected(self):
        self.assertIsNotNone(check_folder_layout("/a/Dropzone", "/a/Dropzone/Excluded"))
        self.assertIsNotNone(check_folder_layout("/a/Dropzone/x", "/a/Dropzone"))
        self.assertIsNotNone(check_folder_layout("/a/Dropzone", "/a/Excluded", "/a/Dropzone/Workspace/s"))
        self.assertIsNone(check_folder_layout("/a/Dropzone", "/a/Excluded", "/a/Workspace/s"))


if __name__ == "__main__":
    unittest.main()
