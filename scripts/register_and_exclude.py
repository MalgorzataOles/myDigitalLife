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
    read_checksum_rows,
    write_checksum_pairs,
    normalize_path,
    has_unsupported_name,
    check_folder_layout,
    get_user_name,
    get_log_path,
    run_log,
    pipeline_lock,
    LOCK_DIRNAME,
    is_ignored_dropzone_file,
    describe_folder_counts,
    TIMESTAMP_FORMAT,
    REGISTRY_FILENAME,
    EXCLUDE_FILENAME,
)


def main():
    config = load_configuration()
    user_name = get_user_name(config)
    log_path = get_log_path(config)

    with run_log(log_path, "register_and_exclude.py", user_name, sys.argv[1:]):
        run(config, user_name)


def run(config, user_name):
    dropzone_path = config.get("dropzone_path")
    excluded_root_dir = config.get("excluded_path")

    if not dropzone_path or not os.path.exists(dropzone_path):
        print(f"❌ Execution Halting: 'dropzone_path' is invalid or inaccessible:\n   '{dropzone_path}'")
        sys.exit(1)

    if not excluded_root_dir:
        print("❌ Execution Halting: 'excluded_path' configuration is completely missing from config.json.")
        sys.exit(1)

    layout_problem = check_folder_layout(dropzone_path, excluded_root_dir, log_path=config.get("log_path"))
    if layout_problem:
        print(f"❌ Execution Halting: {layout_problem}")
        sys.exit(1)

    with pipeline_lock(dropzone_path, "register_and_exclude.py"):
        process(dropzone_path, excluded_root_dir, user_name)


def process(dropzone_path, excluded_root_dir, user_name):
    registry_path = os.path.join(dropzone_path, REGISTRY_FILENAME)
    exclusion_list_path = os.path.join(dropzone_path, EXCLUDE_FILENAME)

    # Pre-load datasets into memory securely before header generation
    exclusion_set = load_checksum_list(exclusion_list_path, is_local_registry=False)
    registered_paths = {
        normalize_path(path) for path in load_checksum_list(registry_path, is_local_registry=True)
    }

    # Dynamic creation of the timestamped isolation folder inside Excluded/
    run_started = datetime.now()
    timestamp = run_started.strftime(TIMESTAMP_FORMAT)
    registered_at = timestamp
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
    unreadable_files = []
    badly_named_files = []
    moved_files = []
    failed_moves = []

    print("🔎 Scanning files ...")

    for root, dirs, files in os.walk(dropzone_path):
        dirs[:] = [d for d in dirs if d != LOCK_DIRNAME]
        for file in files:
            # Skip hidden metadata artifacts and the registry files themselves
            if is_ignored_dropzone_file(file):
                continue

            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, dropzone_path)

            # Case A: Already logged locally, skip configuration check
            if normalize_path(relative_path) in registered_paths:
                continue

            # Tabs/line breaks in a name would corrupt the registry file format
            if has_unsupported_name(relative_path):
                badly_named_files.append(relative_path)
                continue

            # Case B: Brand new file. Calculate signature
            file_hash = calculate_sha256(full_path)
            if not file_hash:
                unreadable_files.append(relative_path)
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
                moved_files.append(rel_path)
            except OSError as e:
                print(f"   ❌ Error shifting file {rel_path} to backup space: {e}")
                failed_moves.append(rel_path)

    # Save and commit new unique additions to the Dropzone registry
    # The registry is replaced in one step (never appended to), so a run that
    # is cut off can't leave a half-written row behind.
    if new_entries:
        rows = read_checksum_rows(registry_path)
        rows += [(file_hash, rel_path, registered_at, user_name) for file_hash, rel_path in new_entries]
        if not write_checksum_pairs(registry_path, rows, f"DROPZONE REGISTRY - UPDATED ON {timestamp}"):
            print("   Nothing was registered in this run. Run this script again.")
            sys.exit(1)

    # Output clear status report
    print("\n" + "=" * 70)
    print(" PROCESSING RUN COMPLETE")
    print("=" * 70)
    print(f" Files registered     : {len(new_entries)}")
    for line in describe_folder_counts([rel_path for _, rel_path in new_entries]):
        print(f"     - {line}")
    print(f" Files excluded       : {len(moved_files)}")
    for line in describe_folder_counts(moved_files):
        print(f"     - {line}")
    if failed_moves:
        print(f" ⚠️  Files NOT moved to Excluded/ (move failed): {len(failed_moves)}")
        for rel_path in sorted(failed_moves):
            print(f"     - {rel_path}")
        print("     They are still in Dropzone and were not registered. Run this script again.")
    if badly_named_files:
        print(f" ⚠️  Files NOT registered (name contains a tab or line break): {len(badly_named_files)}")
        for rel_path in sorted(badly_named_files):
            print(f"     - {rel_path!r}")
        print("     Rename them, then run this script again.")
    if unreadable_files:
        print(f" ⚠️  Files NOT registered (could not be read): {len(unreadable_files)}")
        for rel_path in sorted(unreadable_files):
            print(f"     - {rel_path}")
        print("     They were skipped. Fix the problem and run this script again.")
    if moved_files:
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
