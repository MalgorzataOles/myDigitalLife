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

from scripts.finalize_curation import main
from scripts.common import read_checksum_pairs


class TestFinalizeCurationPipeline(unittest.TestCase):
    """
    Test suite for the rewritten finalize_curation.py: no manifest state,
    hashes Original/ and Sorted/ fresh every run, and reconciles them
    against the Dropzone registry and the shared exclude.sha256 ledger.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dropzone_path = os.path.join(self.test_dir, "Dropzone")
        self.excluded_path = os.path.join(self.test_dir, "Excluded")
        self.session_path = os.path.join(self.test_dir, "Workspace", "Gosia_2026-09-25")
        self.original_path = os.path.join(self.session_path, "Original")
        self.sorted_path = os.path.join(self.session_path, "Sorted")

        os.makedirs(self.dropzone_path, exist_ok=True)
        os.makedirs(self.excluded_path, exist_ok=True)
        os.makedirs(self.original_path, exist_ok=True)
        os.makedirs(self.sorted_path, exist_ok=True)

        self.mock_config = {
            "dropzone_path": self.dropzone_path,
            "excluded_path": self.excluded_path,
        }

        self.registry_path = os.path.join(self.dropzone_path, "registered.sha256")
        self.exclusion_path = os.path.join(self.dropzone_path, "exclude.sha256")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def _run(self, commit=False):
        argv = ["finalize_curation.py", self.session_path]
        if commit:
            argv.append("--commit")
        with patch("scripts.finalize_curation.load_configuration", return_value=self.mock_config):
            with patch.object(sys, "argv", argv):
                main()

    def test_halts_on_missing_original_or_sorted(self):
        shutil.rmtree(self.original_path)
        with patch("scripts.finalize_curation.load_configuration", return_value=self.mock_config):
            with patch.object(sys, "argv", ["finalize_curation.py", self.session_path]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

    def test_aborts_on_duplicate_hash_within_sorted_without_changing_anything(self):
        # Same content filed into two different Sorted categories.
        self._write(os.path.join(self.sorted_path, "Family", "beach.jpg"), b"same_photo")
        self._write(os.path.join(self.sorted_path, "Beach", "beach.jpg"), b"same_photo")

        dropzone_file = os.path.join(self.dropzone_path, "IMG_001.jpg")
        self._write(dropzone_file, b"same_photo")
        from scripts.common import calculate_sha256
        file_hash = calculate_sha256(dropzone_file)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            f.write(f"{file_hash}\tIMG_001.jpg\n")

        with self.assertRaises(SystemExit) as cm:
            self._run(commit=True)
        self.assertEqual(cm.exception.code, 1)

        # Nothing should have moved or changed.
        self.assertTrue(os.path.exists(dropzone_file))
        registry_data = read_checksum_pairs(self.registry_path)
        self.assertEqual(len(registry_data), 1)
        self.assertFalse(os.path.exists(self.exclusion_path))

    def test_dry_run_does_not_modify_anything(self):
        dropzone_file = os.path.join(self.dropzone_path, "IMG_002.jpg")
        self._write(dropzone_file, b"vacation_photo")
        from scripts.common import calculate_sha256
        file_hash = calculate_sha256(dropzone_file)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            f.write(f"{file_hash}\tIMG_002.jpg\n")

        self._write(os.path.join(self.original_path, "IMG_002.jpg"), b"vacation_photo")
        self._write(os.path.join(self.sorted_path, "Trips", "IMG_002.jpg"), b"vacation_photo")

        self._run(commit=False)

        self.assertTrue(os.path.exists(dropzone_file))
        self.assertFalse(os.path.exists(self.exclusion_path))
        registry_data = read_checksum_pairs(self.registry_path)
        self.assertEqual(len(registry_data), 1)

    def test_commit_moves_matched_file_and_prefers_sorted_path_in_ledger(self):
        dropzone_file = os.path.join(self.dropzone_path, "raw", "IMG_003.jpg")
        self._write(dropzone_file, b"birthday_photo")
        from scripts.common import calculate_sha256
        file_hash = calculate_sha256(dropzone_file)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            f.write(f"{file_hash}\traw/IMG_003.jpg\n")

        # Present in both Original and Sorted; Sorted's path should win in the ledger.
        self._write(os.path.join(self.original_path, "IMG_003.jpg"), b"birthday_photo")
        self._write(os.path.join(self.sorted_path, "Birthdays", "2026.jpg"), b"birthday_photo")

        self._run(commit=True)

        # Original Dropzone file is gone, archived under Excluded/curation_.../raw/IMG_003.jpg
        self.assertFalse(os.path.exists(dropzone_file))
        curation_batches = [d for d in os.listdir(self.excluded_path) if d.startswith("curation_")]
        self.assertEqual(len(curation_batches), 1)
        archived_path = os.path.join(self.excluded_path, curation_batches[0], "raw", "IMG_003.jpg")
        self.assertTrue(os.path.exists(archived_path))

        # Registry no longer lists this hash.
        registry_data = read_checksum_pairs(self.registry_path)
        self.assertEqual(len(registry_data), 0)

        # Ledger records the Sorted-relative path, not the Original one.
        exclusion_data = read_checksum_pairs(self.exclusion_path)
        self.assertEqual(len(exclusion_data), 1)
        self.assertEqual(exclusion_data[0], (file_hash, "Birthdays/2026.jpg"))

    def test_file_removed_from_original_is_not_treated_as_handled(self):
        # File exists in Dropzone/registry but the user deleted it from Original
        # entirely (changed their mind before it ever reached Sorted) -> must
        # NOT be archived or excluded.
        dropzone_file = os.path.join(self.dropzone_path, "IMG_004.jpg")
        self._write(dropzone_file, b"unwanted_photo")
        from scripts.common import calculate_sha256
        file_hash = calculate_sha256(dropzone_file)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            f.write(f"{file_hash}\tIMG_004.jpg\n")

        self._run(commit=True)

        self.assertTrue(os.path.exists(dropzone_file))
        registry_data = read_checksum_pairs(self.registry_path)
        self.assertEqual(len(registry_data), 1)
        self.assertFalse(os.path.exists(self.exclusion_path))

    def test_multiple_dropzone_copies_of_same_hash_are_all_moved(self):
        # Two identical files landed in Dropzone under different paths in the
        # same intake batch (a known register_and_exclude.py edge case).
        first_copy = os.path.join(self.dropzone_path, "phone", "IMG_005.jpg")
        second_copy = os.path.join(self.dropzone_path, "sdcard", "IMG_005.jpg")
        self._write(first_copy, b"duplicate_intake_photo")
        self._write(second_copy, b"duplicate_intake_photo")
        from scripts.common import calculate_sha256
        file_hash = calculate_sha256(first_copy)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            f.write(f"{file_hash}\tphone/IMG_005.jpg\n")
            f.write(f"{file_hash}\tsdcard/IMG_005.jpg\n")

        self._write(os.path.join(self.sorted_path, "Kept", "IMG_005.jpg"), b"duplicate_intake_photo")

        self._run(commit=True)

        self.assertFalse(os.path.exists(first_copy))
        self.assertFalse(os.path.exists(second_copy))
        registry_data = read_checksum_pairs(self.registry_path)
        self.assertEqual(len(registry_data), 0)
        exclusion_data = read_checksum_pairs(self.exclusion_path)
        self.assertEqual(len(exclusion_data), 1, "Only one ledger entry, even though two files were archived.")


if __name__ == "__main__":
    unittest.main()
