#!/usr/bin/env python3
import os
import sys
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch

# Adjust system path to ensure the 'scripts' module can be imported from the root layout
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

# Import targeted pipeline components from your production append script
from scripts.append_to_curation import calculate_sha256, main


class TestAppendToCurationPipeline(unittest.TestCase):
    """
    Test suite enforcing code quality and structural logic for append_to_curation.py.
    Uses isolated temporary structures to avoid touching live network volumes.
    """

    def setUp(self):
        # Create a sandbox directory structure for simulating the Workspace layout
        self.test_dir = tempfile.mkdtemp()
        self.dropzone_path = os.path.join(self.test_dir, "Dropzone")
        self.curated_folder = os.path.join(self.test_dir, "Workspace", "Summer_Trip_2026")
        self.appended_folder = os.path.join(self.curated_folder, "appended")
        
        os.makedirs(self.dropzone_path, exist_ok=True)
        os.makedirs(self.appended_folder, exist_ok=True)

        # Mock configuration dictionary matching your production config structure
        self.mock_config = {
            "dropzone_path": self.dropzone_path,
        }

        # Create a baseline manifest file to simulate an active ongoing curation session
        self.manifest_path = os.path.join(self.curated_folder, "session.manifest")
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write("initial_hash_123\tphoto1.jpg\n")

        # Fixed parameters for sample files
        self.sample_content = b"extra_photo_bytes"
        self.expected_hash = "84ef0368c37d04e38e6e580e66d987d603a11b6f00db1019df99b11925b6c2c8"

    def tearDown(self):
        # Obliterate temporary directories to keep the developer machine pristine
        shutil.rmtree(self.test_dir)

    def test_calculate_sha256_functional_check(self):
        """Verifies calculation of a secure file cryptographic hash footprint."""
        sample_file_path = os.path.join(self.appended_folder, "late_photo.jpg")
        with open(sample_file_path, "wb") as f:
            f.write(self.sample_content)

        calculated_hash = calculate_sha256(sample_file_path)
        self.assertEqual(calculated_hash, self.expected_hash)

    @patch("scripts.append_to_curation.load_configuration")
    def test_append_execution_appends_to_existing_manifest(self, mock_load_config):
        """
        Integration test verifying processing mechanics:
        - Scans the designated nested target folder.
        - Calculates the unmutated hash BEFORE curation edits.
        - Safely appends the entry underneath existing manifest content with a separation marker.
        """
        mock_load_config.return_value = self.mock_config

        # Place a late file arrival into the single appended subfolder directory layout
        late_file_name = "missed_backup_photo.png"
        late_file_path = os.path.join(self.appended_folder, late_file_name)
        with open(late_file_path, "wb") as f:
            f.write(self.sample_content)

        # Execute the main pipeline loop by passing the single appended subfolder path via CLI arguments
        with patch.object(sys, "argv", ["append_to_curation.py", self.appended_folder]):
            main()

        # Read the manifest file content to verify modifications
        self.assertTrue(os.path.exists(self.manifest_path), "The manifest file was unexpectedly removed.")
        
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest_lines = f.readlines()

        # Validate that the original baseline line wasn't overwritten (Append Mode Protection)
        self.assertTrue(any("initial_hash_123\tphoto1.jpg" in line for line in manifest_lines))

        # Validate that the batch comment marker line exists
        self.assertTrue(any("APPENDED BATCH:" in line for line in manifest_lines))

        # Validate that the path is cleanly built relative to the curated session folder root
        expected_relative_entry = f"appended/{late_file_name}"
        expected_log_line = f"{self.expected_hash}\t{expected_relative_entry}"
        
        self.assertTrue(
            any(expected_log_line in line.strip() for line in manifest_lines),
            f"Expected log entry line missing from file updates. Searched for: {expected_log_line}"
        )


if __name__ == "__main__":
    unittest.main()