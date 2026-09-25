#!/usr/bin/env python3
import os
import sys
import shutil
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts.common import (
    calculate_sha256,
    load_configuration,
    load_checksum_list,
    REGISTRY_FILENAME,
    EXCLUDE_FILENAME,
)


def main():
    config = load_configuration()

    dropzone_path = config.get("dropzone_path")
    excluded_root_dir = config.get("excluded_path")

    if not dropzone_path or not os.path.exists(dropzone_path):
        print(f"❌ Execution Halting: 'dropzone_path' is invalid or inaccessible:\n   '{dropzone_path}'")
        sys.exit(1)

    if not excluded_root_dir:
        print("❌ Execution Halting: 'excluded_path' configuration is completely missing from config.json.")
        sys.exit(1)

    registry_path = os.path.join(dropzone_path, REGISTRY_FILENAME)
    exclusion_list_path = os.path.join(dropzone_path, EXCLUDE_FILENAME)

    # Pre-load datasets into memory securely before header generation
    exclusion_set = load_checksum_list(exclusion_list_path, is_local_registry=False)
    registered_paths = load_checksum_list(registry_path, is_local_registry=True)

    # Dynamic creation of the timestamped isolation folder inside Excluded/
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    current_batch_excluded_dir = os.path.join(excluded_root_dir, f"registration_{timestamp}")

    # Clean, literal startup dashboard
    print("\n" + "~" * 60)
    print(" 📸 STARTING RUN: Checking for new files...")
    print("~" * 60)
    print(f" Scanning folder   : {dropzone_path}")
    print(f" Registry file     : {REGISTRY_FILENAME}")
    if os.path.exists(exclusion_list_path) and len(exclusion_set) > 0:
        print(f" Exclusion file    : {EXCLUDE_FILENAME} ({len(exclusion_set)} items loaded)")
    print("~" * 60 + "\n")

    new_entries = []
    excluded_files_log = []

    print("🔎 Scanning files ...")

    for root, _, files in os.walk(dropzone_path):
        for file in files:
            # Skip hidden metadata artifacts and the registry files themselves
            if (file.startswith("._") or
                file == ".DS_Store" or
                file == REGISTRY_FILENAME or
                file == EXCLUDE_FILENAME):
                continue

            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, dropzone_path)

            # Case A: Already logged locally, skip configuration check
            if relative_path in registered_paths:
                continue

            # Case B: Brand new file. Calculate signature
            file_hash = calculate_sha256(full_path)
            if not file_hash:
                continue

            # Case C: If found in the exclusion ledger, stage for structured migration
            if file_hash in exclusion_set:
                excluded_files_log.append((full_path, relative_path))
            else:
                # Case D: Safe unique file. Stage to write to the Dropzone registry
                print(f"   [NEW ENTRY] Registered -> {relative_path}")
                new_entries.append((file_hash, relative_path))

    # Perform the structured file movements to 'Excluded/' safely if variations exist
    if excluded_files_log:
        if not os.path.exists(excluded_root_dir):
            try:
                os.makedirs(excluded_root_dir, exist_ok=True)
            except OSError as e:
                print(f"❌ Critical Failure: Could not create your base 'Excluded' folder: {e}")
                sys.exit(1)

        for source_full_path, rel_path in excluded_files_log:
            # Build the identical target structure layout matching the source path tree
            destination_path = os.path.join(current_batch_excluded_dir, rel_path)
            destination_parent_dir = os.path.dirname(destination_path)

            # Ensure the nested path directories exist before copying over file data
            os.makedirs(destination_parent_dir, exist_ok=True)

            print(f"   [ISOLATING] Excluded -> {rel_path}")
            try:
                shutil.move(source_full_path, destination_path)
            except OSError as e:
                print(f"   ❌ Error shifting file {rel_path} to backup space: {e}")

    # Save and commit new unique additions to the Dropzone registry
    if new_entries:
        try:
            with open(registry_path, "a", encoding="utf-8") as f:
                for file_hash, rel_path in new_entries:
                    f.write(f"{file_hash}\t{rel_path}\n")
        except (IOError, OSError) as e:
            print(f"❌ Critical Failure: Could not append entries to local registry: {e}")

    # Output clear status report
    print("\n" + "=" * 70)
    print(" PROCESSING RUN COMPLETE")
    print("=" * 70)
    print(f" Files registered     : {len(new_entries)}")
    print(f" Files excluded       : {len(excluded_files_log)}")
    if excluded_files_log:
        print(f" 📂 Moved to folder : {current_batch_excluded_dir}")
        print("\n" + "─" * 70)
        print("  ⚠️  ACTION REQUIRED: Excluded Files Pending Review")
        print("─" * 70)
        print(f"  Location: {current_batch_excluded_dir}")
        print("  ")
        print("  Next steps:")
        print("  1. Review excluded files - confirm they should be removed")
        print("  2. If you disagree with exclusion: move to a curated folder")
        print("     (NOT back to Dropzone/)")
        print("  3. Delete files when reviewed")
        print("  4. Session complete when Excluded/ is empty")
        print("=" * 70 + "\n")
    else:
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
