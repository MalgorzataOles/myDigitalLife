#!/usr/bin/env python3
import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch

# Adjust system path to ensure the 'scripts' module can be imported from the root layout
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

# Import targeted pipeline components from your production script
from scripts.start_curation import calculate_sha256, main


class TestStartCurationPipeline(unittest.TestCase):
    """
    Test suite enforcing code quality and structural logic for start_curation.py.
    Uses temporary environments to ensure no real data is modified.
    """

    def setUp(self):
        # Create a sandbox directory structure for simulating a manually prepared Workspace folder
        self.test_dir = tempfile.mkdtemp()
        self.curated_folder = os.path.join(self.test_dir, "Workspace", "Summer_Trip_2026")
        os.makedirs(self.curated_folder, exist_ok=True)

        self.manifest_filename = "session.manifest"
        self.manifest_path = os.path.join(self.curated_folder, self.manifest_filename)

        # Fixed parameters for sample files
        self.sample_content = b"photo_bytes_abc"
        self.expected_hash = "6f857bf5761ab48c7a5616b1466653a9b1bbde6481821ad54a97dc5143f7a667"

    def tearDown(self):
        # Clean up temporary directories
        shutil.rmtree(self.test_dir)

    def test_calculate_sha256_functional_check(self):
        """Verifies calculation of a secure file cryptographic hash footprint."""
        sample_file_path = os.path.join(self.curated_folder, "test_image.jpg")
        with open(sample_file_path, "wb") as f:
            f.write(self.sample_content)

        calculated_hash = calculate_sha256(sample_file_path)
        self.assertEqual(calculated_hash, self.expected_hash)

    def test_manifest_generation_and_relative_paths(self):
        """
        Integration test verifying processing mechanics:
        - Scans a manually prepared folder path.
        - Calculates the hashes of all nested files.
        - Generates a pristine session.manifest file inside that folder.
        """
        # Place test files inside the curated folder structure
        file_a_name = "holiday.jpg"
        file_a_path = os.path.join(self.curated_folder, file_a_name)
        with open(file_a_path, "wb") as f:
            f.write(self.sample_content)

        # Place a second file inside a nested subfolder to ensure recursive traversal works
        nested_dir = os.path.join(self.curated_folder, "subfolder")
        os.makedirs(nested_dir, exist_ok=True)
        file_b_name = "document.txt"
        file_b_path = os.path.join(nested_dir, file_b_name)
        with open(file_b_path, "wb") as f:
            f.write(b"different_content_bytes")
            
        file_b_hash = "efcabd4deb856acbca56378c0fd591d6727298aac6bf3705493a4859443fd934"

        # Execute the main pipeline loop by passing the target directory path via CLI arguments
        with patch.object(sys, "argv", ["start_curation.py", self.curated_folder]):
            main()

        # Verifications
        self.assertTrue(os.path.exists(self.manifest_path), "The session.manifest file was not created.")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest_lines = f.readlines()

        # Check for the header comment line
        self.assertTrue(any("ORIGINAL BASELINE CURATION" in line for line in manifest_lines))

        # Check for File A (relative path should just be the filename)
        expected_line_a = f"{self.expected_hash}\t{file_a_name}"
        self.assertTrue(any(expected_line_a in line.strip() for line in manifest_lines))

        # Check for File B (relative path should preserve the nested subfolder)
        expected_relative_path_b = os.path.join("subfolder", file_b_name)
        expected_line_b = f"{file_b_hash}\t{expected_relative_path_b}"
        self.assertTrue(any(expected_line_b in line.strip() for line in manifest_lines))

        # Verify manifest is set to read-only (0o444)
        manifest_mode = os.stat(self.manifest_path).st_mode & 0o777
        self.assertEqual(manifest_mode, 0o444, "Manifest should be read-only")

    def test_safety_halt_prevents_overwriting_existing_manifest(self):
        """Ensures that the script will abort execution if a session.manifest already exists."""
        # Create a pre-existing manifest file to trigger the safety boundary
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write("pre_existing_data\n")

        # Execute the script and verify that it calls sys.exit(1) to protect the file
        with patch.object(sys, "argv", ["start_curation.py", self.curated_folder]):
            with self.assertRaises(SystemExit) as cm:
                main()
            # Assert that it exits with a status code of 1 (error/halt)
            self.assertEqual(cm.exception.code, 1)

    def test_error_on_nonexistent_path(self):
        """Ensures graceful error message when provided path does not exist."""
        nonexistent_path = "/abc/def/ghi/nonexistent_folder"
        
        with patch.object(sys, "argv", ["start_curation.py", nonexistent_path]):
            with self.assertRaises(SystemExit) as cm:
                with patch('sys.stdout') as mock_stdout:
                    main()
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()