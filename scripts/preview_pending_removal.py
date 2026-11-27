#!/usr/bin/env python3
import os
import sys
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts.common import (
    hash_files_in,
    load_configuration,
    load_checksum_list,
    find_unregistered_files,
    describe_folder_counts,
    get_user_name,
    get_log_path,
    get_state_path,
    run_log,
    REGISTRY_FILENAME,
)

ORIGINAL_DIRNAME = "Original"
SORTED_DIRNAME = "Sorted"
PREVIEW_DIRNAME = "ToBeDeleted"


def main():
    if len(sys.argv) < 2:
        print("❌ Execution Error: Missing required session folder path argument.")
        print("Usage: python3 scripts/preview_pending_removal.py /path/to/Workspace/Name_Date")
        sys.exit(1)

    config = load_configuration()
    user_name = get_user_name(config)
    log_path = get_log_path(config)
    state_path = get_state_path(config)

    with run_log(log_path, "preview_pending_removal.py", user_name, sys.argv[1:]):
        run(sys.argv[1], config.get("dropzone_path"), state_path)


def print_registration_status(dropzone_path, state_path):
    """finalize_curation.py refuses to run while Dropzone holds unregistered files, so say so here."""
    if not dropzone_path or not os.path.isdir(dropzone_path):
        print(f" ⚠️  Dropzone could not be checked: '{dropzone_path}' is not reachable.")
        print("=" * 70)
        return
    registry_path = os.path.join(state_path, REGISTRY_FILENAME)
    unregistered = find_unregistered_files(
        dropzone_path, load_checksum_list(registry_path, is_local_registry=True)
    )
    if not unregistered:
        print(" Dropzone: all files are registered.")
        print("=" * 70)
        return
    print(f" ⚠️  Dropzone: {len(unregistered)} file(s) are not registered yet:")
    for line in describe_folder_counts(unregistered):
        print(f"     - {line}")
    print("     Run register_and_exclude.py before finalize_curation.py, which stops otherwise.")
    print("=" * 70)


def run(session_path, dropzone_path, state_path):
    original_path = os.path.join(session_path, ORIGINAL_DIRNAME)
    sorted_path = os.path.join(session_path, SORTED_DIRNAME)
    preview_path = os.path.join(session_path, PREVIEW_DIRNAME)

    if not os.path.isdir(original_path):
        print(f"❌ Execution Halting: No '{ORIGINAL_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)
    if not os.path.isdir(sorted_path):
        print(f"❌ Execution Halting: No '{SORTED_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)

    print("\n" + "~" * 60)
    print(" 👀 PREVIEWING FILES PENDING REMOVAL...")
    print("~" * 60)
    print(f" Original folder : {original_path}")
    print(f" Sorted folder   : {sorted_path}")
    print(f" Preview folder  : {preview_path}")
    print("~" * 60 + "\n")

    unreadable = []
    print("🔎 Hashing Sorted/ ...")
    sorted_hashes = set(hash_files_in(sorted_path, unreadable).values())

    print("🔎 Hashing Original/ ...")
    original_entries = hash_files_in(original_path, unreadable)

    pending_removal = sorted(
        rel_path for rel_path, file_hash in original_entries.items()
        if file_hash not in sorted_hashes
    )

    # ToBeDeleted/ is fully derived from the current state of Original/ and
    # Sorted/, so it's always safe (and correct) to regenerate it from
    # scratch rather than trust whatever was left over from a previous run.
    if os.path.exists(preview_path):
        shutil.rmtree(preview_path)

    if pending_removal:
        os.makedirs(preview_path, exist_ok=True)
        for rel_path in pending_removal:
            source_path = os.path.join(original_path, rel_path)
            destination_path = os.path.join(preview_path, rel_path)
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.copy2(source_path, destination_path)
            print(f"   [PENDING REMOVAL] {rel_path}")

    print("\n" + "=" * 70)
    print(" PREVIEW COMPLETE")
    print("=" * 70)
    print(f" Files in Original/      : {len(original_entries)}")
    print(f" Files pending removal   : {len(pending_removal)}")
    if pending_removal:
        print(f" 📂 Review copies placed in : {preview_path}")
        print("\n" + "─" * 70)
        print("  To keep a file after all: copy it from ToBeDeleted/ into Sorted/")
        print("  before running finalize_curation.py.")
        print("─" * 70)
    print("=" * 70)
    print_registration_status(dropzone_path, state_path)
    if unreadable:
        print(f" ⚠️  {len(unreadable)} file(s) could not be read and are NOT part of this preview:")
        for rel_path in sorted(unreadable):
            print(f"     - {rel_path}")
        print("     finalize_curation.py will refuse to run until this is fixed.")
        print("=" * 70)
    print()


if __name__ == "__main__":
    main()
