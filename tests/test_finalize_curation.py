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
from scripts.finalize_curation import read_checksum_file_lines, main


class TestFinalizeCurationPipeline(unittest.TestCase):
    """
    Test suite enforcing code quality, dry-run safety gates, and capsule isolation 
    mechanics for finalize_curation.py.
    """

    def setUp(self):
        # Create a sandbox directory structure simulating your network storage volume
        self.test_dir = tempfile.mkdtemp()
        self.dropzone_path = os.path.join(self.test_dir, "Dropzone")
        self.workspace_path = os.path.join(self.test_dir, "Workspace")
        self.cleared_path = os.path.join(self.test_dir, "Cleared")
        
        # Explicit folder session within workspace
        self.curated_folder = os.path.join(self.workspace_path, "Summer_Trip_2026")
        
        os.makedirs(self.dropzone_path, exist_ok=True)
        os.makedirs(self.curated_folder, exist_ok=True)
        os.makedirs(self.cleared_path, exist_ok=True)

        # Mock configuration dictionary matching your production config structure
        self.mock_config = {
            "dropzone_path": self.dropzone_path,
            "cleared_path": self.cleared_path
        }

        # Set up a master exclude list target in the simulated repo root
        self.master_exclusion_path = os.path.join(self.test_dir, "exclude.sha256")
        
        # Fixed parameters for mock files
        self.file_hash_1 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"  # content: "hello"
        self.file_hash_2 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # content: empty
        
        self.relative_path_1 = "Phone_Dump/DCIM/photo1.jpg"
        self.relative_path_2 = "Laptop_Dump/Documents/notes.txt"

        # Populate the primary Dropzone folder with physical files
        self.dz_file_1 = os.path.join(self.dropzone_path, self.relative_path_1)
        self.dz_file_2 = os.path.join(self.dropzone_path, self.relative_path_2)
        os.makedirs(os.path.dirname(self.dz_file_1), exist_ok=True)
        os.makedirs(os.path.dirname(self.dz_file_2), exist_ok=True)
        
        with open(self.dz_file_1, "wb") as f:
            f.write(b"hello")
        with open(self.dz_file_2, "wb") as f:
            f.write(b"")

        # Write the baseline primary Dropzone registry file
        self.dz_registry_path = os.path.join(self.dropzone_path, "Dropzone.registered.sha256")
        with open(self.dz_registry_path, "w", encoding="utf-8") as f:
            f.write(f"{self.file_hash_1}\t{self.relative_path_1}\n")
            f.write(f"{self.file_hash_2}\t{self.relative_path_2}\n")

        # Write the workspace session.manifest to simulate that file_hash_1 was curated
        self.manifest_path = os.path.join(self.curated_folder, "session.manifest")
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write(f"{self.file_hash_1}\tphoto1.jpg\n")

        # Place a modified/new curated keeper file directly inside the Workspace folder
        self.keeper_file_path = os.path.join(self.curated_folder, "color_corrected.jpg")
        with open(self.keeper_file_path, "wb") as f:
            f.write(b"curated_photo_modifications")
        self.keeper_hash = "679808381bf482d8c304d9c79238e6e580e66d987d603a11b6f00db1019df99b"

    def tearDown(self):
        # Obliterate temporary sandbox directories
        shutil.rmtree(self.test_dir)

    @patch("scripts.finalize_curation.load_configuration")
    @patch("scripts.finalize_curation.REPO_ROOT")
    def test_dry_run_mode_simulates_without_touching_files(self, mock_repo_root, mock_load_config):
        """Verifies that default Dry-Run execution leaves all files and registries unaltered."""
        mock_load_config.return_value = self.mock_config
        mock_repo_root.return_value = self.test_dir

        # Run script in default safety mode (No --commit flag passed)
        with patch.object(sys, "argv", ["finalize_curation.py", self.curated_folder]):
            main()

        # Assertions for safety: No modifications should exist on disk
        self.assertTrue(os.path.exists(self.dz_file_1), "Dry run modified original file.")
        self.assertFalse(os.path.exists(self.master_exclusion_path), "Dry run created exclusion file.")
        
        # Verify dropzone registry remains unchanged
        dz_registry_data = read_checksum_file_lines(self.dz_registry_path)
        self.assertEqual(len(dz_registry_data), 2)
        
        # Verify no Cleared timestamped directories were initialized
        self.assertEqual(len(os.listdir(self.cleared_path)), 0)

    @patch("scripts.finalize_curation.load_configuration")
    @patch("scripts.finalize_curation.REPO_ROOT")
    def test_commit_mode_executes_full_pipeline_cleanout(self, mock_repo_root, mock_load_config):
        """
        Integration test verifying execution mechanics:
        - Replicates processed files to dated capsule inside Cleared/ preserving tree paths.
        - Generates internal historical receipt registry in that capsule folder.
        - Purges processed files out of the primary Dropzone directory.
        - Updates primary Dropzone registry to remove isolated data entries.
        - Appends fresh curation workspace hashes to master exclude sheet list.
        """
        mock_load_config.return_value = self.mock_config
        mock_repo_root.return_value = self.test_dir

        # Run script in execution mode by including the explicit safety release flag
        with patch.object(sys, "argv", ["finalize_curation.py", self.curated_folder, "--commit"]):
            main()

        # 1. Check isolation capsule deployment inside Cleared/
        timestamped_folders = os.listdir(self.cleared_path)
        self.assertEqual(len(timestamped_folders), 1)
        capsule_dir = os.path.join(self.cleared_path, timestamped_folders[0])

        # 2. Check structure tree replication of the file inside the capsule
        expected_capsule_file_path = os.path.join(capsule_dir, self.relative_path_1)
        self.assertTrue(os.path.exists(expected_capsule_file_path))

        # 3. Check historical receipt registry existence inside that capsule folder
        capsule_receipt_path = os.path.join(capsule_dir, "Dropzone.registered.sha256")
        self.assertTrue(os.path.exists(capsule_receipt_path))
        receipt_rows = read_checksum_file_lines(capsule_receipt_path)
        self.assertIn(self.relative_path_1, receipt_rows[0])

        # 4. Check that processed file was successfully removed from the raw Dropzone space
        self.assertFalse(os.path.exists(self.dz_file_1))
        
        # 5. Check that uncurated files (Laptop_Dump) are cleanly preserved in Dropzone
        self.assertTrue(os.path.exists(self.dz_file_2))

        # 6. Check that primary active Dropzone registry was accurately updated
        updated_dz_registry_rows = read_checksum_file_lines(self.dz_registry_path)
        self.assertEqual(len(updated_dz_registry_rows), 1)
        self.assertEqual(updated_dz_registry_rows[0][1], self.relative_path_2)

        # 7. Check that master exclusion text sheet holds our new curation workspace hashes
        self.assertTrue(os.path.exists(self.master_exclusion_path))
        master_rows = read_checksum_file_lines(self.master_exclusion_path)
        
        # Extracted set of hashes logged to the master exclusion sheet list
        master_hashes = {row[0] for row in master_rows}
        self.assertIn(self.keeper_hash, master_hashes)


if __name__ == "__main__":
    unittest.main()