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
    folders_that_become_empty,
)


class WorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dropzone = os.path.join(self.test_dir, "Dropzone")
        self.excluded = os.path.join(self.test_dir, "Excluded")
        self.session = os.path.join(self.test_dir, "Workspace", "Gosia_20260925")
        os.makedirs(self.dropzone)
        self.state = os.path.join(self.test_dir, "State")
        os.makedirs(self.state)
        os.makedirs(os.path.join(self.session, "Original"))
        os.makedirs(os.path.join(self.session, "Sorted"))
        self.config = {"dropzone_path": self.dropzone, "excluded_path": self.excluded, "user_name": "Tester",
                       "log_path": os.path.join(self.test_dir, "Logs"),
                       "state_path": self.state}
        self.registry = os.path.join(self.state, "registered.sha256")
        self.ledger = os.path.join(self.state, "exclude.sha256")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def run_script(self, module, *args):
        """Runs a script's main() with the test config and returns what it printed."""
        output = io.StringIO()
        try:
            with patch.object(module, "load_configuration", return_value=self.config, create=True):
                with patch.object(sys, "argv", [module.__name__, *args]):
                    with redirect_stdout(output):
                        module.main()
        finally:
            self.last_output = output.getvalue()
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
        self.run_script(preview_pending_removal, self.session)
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


class TestUserName(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")

    def assert_both_scripts_refuse(self):
        for run in (self.register, lambda: self.finalize("--dry-run")):
            with self.assertRaises(SystemExit) as cm:
                run()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("user_name", self.last_output)
        self.assertFalse(os.path.exists(self.registry), "nothing may be registered without a name")

    def test_missing_user_name_stops_both_scripts(self):
        del self.config["user_name"]
        self.assert_both_scripts_refuse()

    def test_placeholder_user_name_stops_both_scripts(self):
        self.config["user_name"] = "CHANGE_ME"
        self.assert_both_scripts_refuse()

    def test_blank_user_name_stops_both_scripts(self):
        self.config["user_name"] = "   "
        self.assert_both_scripts_refuse()

    def test_name_is_recorded_in_registry_and_ledger_with_a_timestamp(self):
        self.config["user_name"] = "Gosia"
        self.register()
        rows = read_checksum_rows(self.registry)
        self.assertEqual(len(rows[0]), 4)
        self.assertEqual(rows[0][3], "Gosia")

        self.config["user_name"] = "Anna"
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        ledger_rows = read_checksum_rows(self.ledger)
        self.assertEqual(len(ledger_rows), 1)
        file_hash, path, timestamp, user = ledger_rows[0]
        self.assertRegex(timestamp, r"^\d{8}_\d{6}$")
        self.assertEqual(user, "Anna")
        archived_batches = os.listdir(self.excluded)
        self.assertEqual(archived_batches, [f"curation_{timestamp}"], "ledger timestamp must match the folder name")


class TestRunLog(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.test_dir, "Logs")
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")

    def only_log(self) -> str:
        names = os.listdir(self.logs)
        self.assertEqual(len(names), 1, names)
        with open(os.path.join(self.logs, names[0]), encoding="utf-8") as f:
            return names[0], f.read()

    def test_log_contains_header_terminal_output_and_footer(self):
        self.register()
        name, log = self.only_log()
        self.assertRegex(name, r"^\d{8}_\d{6}_register_and_exclude_Tester\.log$")
        self.assertIn("# user      : Tester", log)
        self.assertIn("# script    : register_and_exclude.py", log)
        self.assertIn("[NEW ENTRY] Registered -> Phone1", log)
        self.assertIn("PROCESSING RUN COMPLETE", log)
        self.assertIn("# result    : finished normally", log)

    def test_finalize_dry_run_is_logged_with_its_arguments(self):
        self.register()
        self.finalize("--dry-run")
        logs = sorted(os.listdir(self.logs))
        self.assertEqual(len(logs), 2)
        with open(os.path.join(self.logs, [n for n in logs if "finalize" in n][0]), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("--dry-run", log)
        self.assertIn("DRY-RUN ONLY", log)

    def test_two_runs_in_the_same_second_get_separate_logs(self):
        self.register()
        self.register()
        self.assertEqual(len(os.listdir(self.logs)), 2)

    def test_preview_is_logged(self):
        self.run_script(preview_pending_removal, self.session)
        _, log = self.only_log()
        self.assertIn("# script    : preview_pending_removal.py", log)
        self.assertIn("PREVIEW COMPLETE", log)

    def test_a_crash_is_logged_with_the_full_error(self):
        with patch.object(register_and_exclude, "process", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.register()
        _, log = self.only_log()
        self.assertIn("Traceback", log)
        self.assertIn("RuntimeError: boom", log)
        self.assertIn("# result    : CRASHED", log)

    def test_a_run_stopped_by_the_lock_is_logged(self):
        os.mkdir(os.path.join(self.state, ".pipeline.lock"))
        with self.assertRaises(SystemExit):
            self.register()
        _, log = self.only_log()
        self.assertIn("another run is in progress", log)
        self.assertIn("# result    : stopped with exit status 1", log)

    def test_missing_or_placeholder_log_path_stops_the_run(self):
        for value in (None, "", "/path/to/your/storage/Logs"):
            with self.subTest(log_path=value):
                if value is None:
                    del self.config["log_path"]
                else:
                    self.config["log_path"] = value
                with self.assertRaises(SystemExit) as cm:
                    self.register()
                self.assertEqual(cm.exception.code, 1)
                self.assertIn("log_path", self.last_output)
                self.assertFalse(os.path.exists(self.registry))

    def test_log_folder_inside_dropzone_is_refused(self):
        self.config["log_path"] = os.path.join(self.dropzone, "Logs")
        with self.assertRaises(SystemExit):
            self.register()
        self.assertFalse(os.path.exists(self.registry))

    def test_unwritable_log_folder_stops_the_run(self):
        blocker = os.path.join(self.test_dir, "not_a_folder")
        open(blocker, "w").close()
        self.config["log_path"] = os.path.join(blocker, "Logs")
        with self.assertRaises(SystemExit):
            self.register()
        self.assertFalse(os.path.exists(self.registry))


class TestEmptyFolderCleanup(WorkflowTestCase):
    def day(self, source="Phone1", date="20260920"):
        return os.path.join(self.dropzone, source, date)

    def test_emptied_date_folder_is_removed_but_the_source_folder_stays(self):
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        output = self.finalize("--commit")
        self.assertFalse(os.path.exists(self.day()))
        self.assertTrue(os.path.isdir(os.path.join(self.dropzone, "Phone1")))
        self.assertIn("REMOVED", output)

    def test_dry_run_lists_the_folders_but_removes_nothing(self):
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        output = self.finalize("--dry-run")
        self.assertIn("WILL REMOVE", output)
        self.assertTrue(os.path.exists(os.path.join(self.day(), "a.jpg")))

    def test_hidden_finder_files_do_not_keep_a_folder_alive(self):
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.write(os.path.join(self.day(), ".DS_Store"), b"x")
        self.write(os.path.join(self.day(), "._a.jpg"), b"x")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.assertFalse(os.path.exists(self.day()))

    def test_a_folder_that_still_holds_files_is_kept(self):
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.write(os.path.join(self.day(), "b.jpg"), b"b")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.assertTrue(os.path.exists(os.path.join(self.day(), "b.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.day(), "a.jpg")))

    def test_nested_empty_folders_are_removed_up_to_the_source_level(self):
        self.write(os.path.join(self.day(), "album", "deep", "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.assertFalse(os.path.exists(self.day()))
        self.assertTrue(os.path.isdir(os.path.join(self.dropzone, "Phone1")))

    def test_an_unrelated_empty_folder_is_left_alone(self):
        os.makedirs(self.day("Phone2", "20261001"))  # someone just created it, nothing moved from it
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.assertTrue(os.path.isdir(self.day("Phone2", "20261001")))

    def test_register_removes_the_folder_a_duplicate_was_moved_out_of(self):
        self.write(os.path.join(self.day("Phone1", "20260920"), "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.write(os.path.join(self.day("Phone2", "20261001"), "again.jpg"), b"a")
        output = self.register()
        self.assertFalse(os.path.exists(self.day("Phone2", "20261001")))
        self.assertTrue(os.path.isdir(os.path.join(self.dropzone, "Phone2")))
        self.assertIn("Empty folders removed", output)

    def test_rerun_after_interruption_before_the_cleanup_still_cleans_up(self):
        self.write(os.path.join(self.day(), "a.jpg"), b"a")
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        with patch("scripts.finalize_curation.remove_folders", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.finalize("--commit")
        self.assertEqual(len(read_checksum_rows(self.registry)), 1)
        self.finalize("--commit")
        self.assertFalse(os.path.exists(self.day()))
        self.assertEqual(len(read_checksum_rows(self.registry)), 0)

    def test_files_directly_in_the_source_folder_never_remove_it(self):
        self.assertEqual(folders_that_become_empty(self.dropzone, ["Phone1/a.jpg", "b.jpg"]), [])


class TestStateFolder(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.write(os.path.join(self.dropzone, "Phone1", "20260920", "a.jpg"), b"a")

    def test_registry_ledger_and_lock_live_in_the_state_folder_not_in_dropzone(self):
        self.register()
        self.write(os.path.join(self.session, "Sorted", "a.jpg"), b"a")
        self.finalize("--commit")
        self.assertEqual(sorted(os.listdir(self.state)), ["exclude.sha256", "registered.sha256"])
        for name in os.listdir(self.dropzone):
            self.assertNotIn(".sha256", name)
            self.assertNotEqual(name, ".pipeline.lock")

    def test_lock_is_taken_in_the_state_folder_while_running(self):
        seen = {}
        original_process = register_and_exclude.process

        def spy(*args, **kwargs):
            seen["lock_in_state"] = os.path.isdir(os.path.join(self.state, ".pipeline.lock"))
            seen["lock_in_dropzone"] = os.path.exists(os.path.join(self.dropzone, ".pipeline.lock"))
            return original_process(*args, **kwargs)

        with patch.object(register_and_exclude, "process", side_effect=spy):
            self.register()
        self.assertEqual(seen, {"lock_in_state": True, "lock_in_dropzone": False})
        self.assertFalse(os.path.exists(os.path.join(self.state, ".pipeline.lock")))

    def test_state_folder_is_created_when_missing(self):
        shutil.rmtree(self.state)
        self.register()
        self.assertTrue(os.path.exists(self.registry))

    def test_missing_or_placeholder_state_path_stops_both_scripts(self):
        for value in (None, "", "/path/to/your/storage/State"):
            with self.subTest(state_path=value):
                if value is None:
                    del self.config["state_path"]
                else:
                    self.config["state_path"] = value
                for run in (self.register, lambda: self.finalize("--dry-run")):
                    with self.assertRaises(SystemExit) as cm:
                        run()
                    self.assertEqual(cm.exception.code, 1)
                    self.assertIn("state_path", self.last_output)

    def test_state_folder_inside_dropzone_is_refused(self):
        self.config["state_path"] = os.path.join(self.dropzone, "State")
        with self.assertRaises(SystemExit):
            self.register()
        self.assertFalse(os.path.exists(os.path.join(self.dropzone, "State")))

    def test_old_registry_or_ledger_still_in_dropzone_stops_the_run_with_instructions(self):
        self.write(os.path.join(self.dropzone, "registered.sha256"), b"abc\tx\n")
        for run in (self.register, lambda: self.finalize("--dry-run")):
            with self.assertRaises(SystemExit) as cm:
                run()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("registered.sha256 found inside the Dropzone", self.last_output)
            self.assertIn("Move them there", self.last_output)
        self.assertFalse(os.path.exists(self.registry))


if __name__ == "__main__":
    unittest.main()
