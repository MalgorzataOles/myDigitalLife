#!/usr/bin/env python3
import os
import sys
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from datetime import datetime

# Adjust system path to ensure the 'scripts' module can be imported from the root layout
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

# Import the targeted pipeline functions from your production script
from scripts.register_and_exclude import calculate_sha256, load_checksum_list, main


class TestRegisterAndExcludePipeline(unittest.TestCase):
    """
    Test suite enforcing code quality and structural logic for register_and_exclude.py.
    Uses temporary environments to ensure no real family archives are touched during evaluation.
    """

    def setUp(self):
        # Create a sandbox directory structure for simulating QNAP mounts
        self.test_dir = tempfile.mkdtemp()
        self.dropzone_path = os.path.join(self.test_dir, "Dropzone")
        self.excluded_path = os.path.join(self.test_dir, ".Excluded")
        
        os.makedirs(self.dropzone_path, exist_ok=True)
        os.makedirs(self.excluded_path, exist_ok=True)

        # Mock configuration dictionary matching your production config structure
        self.mock_config = {
            "dropzone_path": self.dropzone_path,
            "excluded_path": self.excluded_path
        }

        # Create a test file with known content to compute explicit expected hash value
        # Word "hello" evaluates to this specific SHA-256 fingerprint:
        self.sample_content = b"hello"
        self.expected_hash = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def tearDown(self):
        # Obliterate temporary directories to keep the developer machine pristine
        shutil.rmtree(self.test_dir)

    def test_calculate_sha256_valid_file(self):
        """Verifies calculation of a secure file cryptographic hash footprint."""
        sample_file_path = os.path.join(self.dropzone_path, "test_file.txt")
        with open(sample_file_path, "wb") as f:
            f.write(self.sample_content)

        calculated_hash = calculate_sha256(sample_file_path)
        self.assertEqual(calculated_hash, self.expected_hash)

    def test_calculate_sha256_missing_file(self):
        """Ensures that missing files handle OS errors gracefully instead of crashing."""
        bad_path = os.path.join(self.dropzone_path, "ghost_file.missing")
        calculated_hash = calculate_sha256(bad_path)
        self.assertIsNone(calculated_hash)

    def test_load_checksum_list_as_exclusion_source(self):
        """Validates extraction of hash fingerprints (Index 0) from tab-separated lists."""
        dummy_list_path = os.path.join(self.test_dir, "test.excluded.sha256")
        with open(dummy_list_path, "w", encoding="utf-8") as f:
            f.write(f"{self.expected_hash}\trelative/path/to/file.jpg\n")
            f.write("# This comment line should be cleanly skipped\n")
            f.write("\n")  # Empty line check

        parsed_exclusions = load_checksum_list(dummy_list_path, is_local_registry=False)
        self.assertIn(self.expected_hash, parsed_exclusions)
        self.assertEqual(len(parsed_exclusions), 1)

    def test_load_checksum_list_as_local_registry(self):
        """Validates tracking of relative directory paths (Index 1) inside registries."""
        dummy_list_path = os.path.join(self.test_dir, "test.registered.sha256")
        target_relative_path = "abc/bcd/def.txt"
        with open(dummy_list_path, "w", encoding="utf-8") as f:
            f.write(f"{self.expected_hash}\t{target_relative_path}\n")

        parsed_registry = load_checksum_list(dummy_list_path, is_local_registry=True)
        self.assertIn(target_relative_path, parsed_registry)
        self.assertEqual(len(parsed_registry), 1)

    @patch("scripts.register_and_exclude.load_configuration")
    def test_end_to_end_pipeline_processing(self, mock_load_config):
        """
        Integration test verifying processing mechanics:
        - Registers fresh files into the registry tracker.
        - Captures matching exclusions and moves them into a structured layout inside Excluded/.
        """
        mock_load_config.return_value = self.mock_config

        # 1. Establish an exclusion fingerprint match constraint for the 'Dropzone' folder name
        exclusion_file_path = os.path.join(self.dropzone_path, "Dropzone.excluded.sha256")
        with open(exclusion_file_path, "w", encoding="utf-8") as f:
            f.write(f"{self.expected_hash}\tany_old_path/photo.jpg\n")

        # 2. Build structured files inside the target directory dropzone
        # File A: A completely new unique file (will be registered)
        unique_file_dir = os.path.join(self.dropzone_path, "unique_folder")
        os.makedirs(unique_file_dir, exist_ok=True)
        unique_file_path = os.path.join(unique_file_dir, "unique.txt")
        with open(unique_file_path, "wb") as f:
            f.write(b"completely_different_content_string")

        # File B: A duplicate file matching the active exclusion hash (will be moved)
        nested_duplicate_dir = os.path.join(self.dropzone_path, "abc", "bcd")
        os.makedirs(nested_duplicate_dir, exist_ok=True)
        duplicate_file_path = os.path.join(nested_duplicate_dir, "def.txt")
        with open(duplicate_file_path, "wb") as f:
            f.write(self.sample_content) # Writes "hello", matches the exclusion hash

        # 3. Execute the pipeline main application loop safely using empty CLI parameters
        with patch.object(sys, "argv", ["register_and_exclude.py"]):
            main()

        # 4. CRITICAL VERIFICATIONS:
        # Check A: The unique file must remain in place inside Dropzone
        self.assertTrue(os.path.exists(unique_file_path))

        # Check B: The unique file relative path must be committed to the registered registry
        registry_file_path = os.path.join(self.dropzone_path, "Dropzone.registered.sha256")
        self.assertTrue(os.path.exists(registry_file_path))
        registry_data = load_checksum_list(registry_file_path, is_local_registry=True)
        self.assertIn("unique_folder/unique.txt", registry_data)

        # Check C: The excluded duplicate must vanish from the raw Dropzone space
        self.assertFalse(os.path.exists(duplicate_file_path))

        # Check D: The duplicate file structure tree must be preserved inside the .Excluded folder
        # We search inside .Excluded/Dropzone/ for a timestamped folder containing our nested directories
        dropzone_excluded_path = os.path.join(self.excluded_path, "Dropzone")
        timestamped_folders = os.listdir(dropzone_excluded_path)
        self.assertEqual(len(timestamped_folders), 1, "A timestamped batch folder should have been created.")
        
        expected_moved_location = os.path.join(
            dropzone_excluded_path, timestamped_folders[0], "abc", "bcd", "def.txt"
        )
        self.assertTrue(os.path.exists(expected_moved_location), "The file structure layout was broken during movement.")


if __name__ == "__main__":
    unittest.main()