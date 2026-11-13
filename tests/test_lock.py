#!/usr/bin/env python3
import io
import os
import sys
import json
import signal
import socket
import shutil
import subprocess
import unittest
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts import register_and_exclude, finalize_curation
from scripts.common import pipeline_lock, find_unregistered_files, LOCK_DIRNAME, LOCK_OWNER_FILENAME


def dead_process_id() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


class TestPipelineLock(unittest.TestCase):
    def setUp(self):
        self.dropzone = tempfile.mkdtemp()
        self.lock_path = os.path.join(self.dropzone, LOCK_DIRNAME)

    def tearDown(self):
        shutil.rmtree(self.dropzone)

    def make_lock(self, **owner):
        os.mkdir(self.lock_path)
        with open(os.path.join(self.lock_path, LOCK_OWNER_FILENAME), "w") as f:
            json.dump(owner, f)

    def acquire(self):
        output = io.StringIO()
        with redirect_stdout(output):
            with pipeline_lock(self.dropzone, "test.py"):
                pass
        return output.getvalue()

    def test_lock_exists_only_while_held(self):
        with pipeline_lock(self.dropzone, "test.py"):
            self.assertTrue(os.path.isdir(self.lock_path))
        self.assertFalse(os.path.exists(self.lock_path))

    def test_second_run_is_blocked_and_told_who_holds_the_lock(self):
        self.make_lock(script="finalize_curation.py", user="anna", host="MacBook-Anna",
                       pid=os.getpid(), started="20260925_143207")
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                with pipeline_lock(self.dropzone, "test.py"):
                    self.fail("the lock must not be granted")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("anna", output.getvalue())
        self.assertIn("MacBook-Anna", output.getvalue())
        self.assertTrue(os.path.isdir(self.lock_path), "the other run's lock must stay")

    def test_lock_is_released_after_an_error(self):
        with self.assertRaises(RuntimeError):
            with pipeline_lock(self.dropzone, "test.py"):
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(self.lock_path))

    def test_lock_is_released_after_ctrl_c(self):
        with self.assertRaises(KeyboardInterrupt):
            with pipeline_lock(self.dropzone, "test.py"):
                raise KeyboardInterrupt()
        self.assertFalse(os.path.exists(self.lock_path))

    def test_lock_is_released_when_the_process_is_terminated(self):
        with self.assertRaises(SystemExit):
            with pipeline_lock(self.dropzone, "test.py"):
                os.kill(os.getpid(), signal.SIGTERM)
        self.assertFalse(os.path.exists(self.lock_path))

    def test_stale_lock_from_a_dead_process_on_this_computer_is_removed(self):
        self.make_lock(script="x.py", user="me", host=socket.gethostname(),
                       pid=dead_process_id(), started="20260101_000000")
        output = self.acquire()
        self.assertIn("leftover lock", output)
        self.assertFalse(os.path.exists(self.lock_path))

    def test_lock_from_another_computer_is_never_removed_automatically(self):
        self.make_lock(script="x.py", user="anna", host="some-other-computer",
                       pid=dead_process_id(), started="20260101_000000")
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                with pipeline_lock(self.dropzone, "test.py"):
                    self.fail("the lock must not be granted")
        self.assertTrue(os.path.isdir(self.lock_path))

    def test_lock_without_owner_info_blocks_instead_of_being_removed(self):
        os.mkdir(self.lock_path)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                with pipeline_lock(self.dropzone, "test.py"):
                    self.fail("the lock must not be granted")
        self.assertTrue(os.path.isdir(self.lock_path))

    def test_lock_folder_is_not_mistaken_for_unregistered_files(self):
        with pipeline_lock(self.dropzone, "test.py"):
            self.assertEqual(find_unregistered_files(self.dropzone, set()), [])


class TestScriptsRespectTheLock(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dropzone = os.path.join(self.test_dir, "Dropzone")
        self.excluded = os.path.join(self.test_dir, "Excluded")
        self.session = os.path.join(self.test_dir, "Workspace", "Gosia_20260925")
        for folder in (self.dropzone, os.path.join(self.session, "Original"), os.path.join(self.session, "Sorted")):
            os.makedirs(folder)
        self.config = {"dropzone_path": self.dropzone, "excluded_path": self.excluded, "user_name": "Tester"}
        os.mkdir(os.path.join(self.dropzone, LOCK_DIRNAME))
        with open(os.path.join(self.dropzone, "a.jpg"), "wb") as f:
            f.write(b"a")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def run_blocked(self, module, *args):
        with patch.object(module, "load_configuration", return_value=self.config):
            with patch.object(sys, "argv", [module.__name__, *args]):
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        module.main()
        self.assertEqual(cm.exception.code, 1)

    def test_register_does_nothing_while_another_run_holds_the_lock(self):
        self.run_blocked(register_and_exclude)
        self.assertFalse(os.path.exists(os.path.join(self.dropzone, "registered.sha256")))

    def test_finalize_does_nothing_while_another_run_holds_the_lock(self):
        self.run_blocked(finalize_curation, self.session, "--commit")
        self.assertFalse(os.path.exists(os.path.join(self.dropzone, "exclude.sha256")))


if __name__ == "__main__":
    unittest.main()
