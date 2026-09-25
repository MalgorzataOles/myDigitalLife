#!/usr/bin/env python3
import os
import sys
import shutil
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from scripts.common import (
    load_configuration,
    read_checksum_pairs,
    hash_files_in,
    REGISTRY_FILENAME,
    EXCLUDE_FILENAME,
)

ORIGINAL_DIRNAME = "Original"
SORTED_DIRNAME = "Sorted"


def write_checksum_pairs(file_path: str, records: list, header_text: str) -> None:
    """Writes/overwrites a checksum file cleanly using tab separation formatting."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {header_text}\n")
            for file_hash, rel_path in records:
                f.write(f"{file_hash}\t{rel_path}\n")
    except (IOError, OSError) as e:
        print(f"❌ Critical Failure: Could not write updates to {file_path}: {e}")


def find_duplicate_hashes(entries: dict) -> dict:
    """Given {relative_path: hash}, returns {hash: [relative_paths]} for hashes seen more than once."""
    by_hash = defaultdict(list)
    for rel_path, file_hash in entries.items():
        by_hash[file_hash].append(rel_path)
    return {file_hash: paths for file_hash, paths in by_hash.items() if len(paths) > 1}


def main():
    args = sys.argv[1:]
    is_dry_run = True
    if "--commit" in args:
        is_dry_run = False
        args.remove("--commit")

    if not args:
        print("❌ Execution Error: Missing required session folder path argument.")
        print("")
        print("Usage:")
        print("  (Dry-Run) : python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date")
        print("  (Commit)  : python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date --commit")
        sys.exit(1)

    session_path = args[0]
    original_path = os.path.join(session_path, ORIGINAL_DIRNAME)
    sorted_path = os.path.join(session_path, SORTED_DIRNAME)

    if not os.path.isdir(original_path):
        print(f"❌ Execution Halting: No '{ORIGINAL_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)
    if not os.path.isdir(sorted_path):
        print(f"❌ Execution Halting: No '{SORTED_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)

    config = load_configuration()
    dropzone_path = config.get("dropzone_path")
    excluded_root_dir = config.get("excluded_path")

    if not dropzone_path or not os.path.exists(dropzone_path):
        print(f"❌ Execution Halting: 'dropzone_path' is invalid or inaccessible:\n   '{dropzone_path}'")
        sys.exit(1)
    if not excluded_root_dir:
        print("❌ Execution Halting: 'excluded_path' configuration is missing from config.json.")
        sys.exit(1)

    print("\n" + "~" * 60)
    if is_dry_run:
        print(" 👀 RUNNING IN DRY-RUN MODE: Previewing proposed steps...")
    else:
        print(" 📸 EXECUTING CURATION FINALIZATION...")
    print("~" * 60)
    print(f" Session folder  : {session_path}")
    print(f" Dropzone        : {dropzone_path}")
    print(f" Excluded folder : {excluded_root_dir}")
    print("~" * 60 + "\n")

    # Step 0 (always first, before any mutation): refuse to continue if the
    # same content was filed into two different places inside Sorted/ - we
    # have no way to know which final path is the "real" one.
    print("🔎 Hashing Sorted/ ...")
    sorted_entries = hash_files_in(sorted_path)
    duplicates = find_duplicate_hashes(sorted_entries)
    if duplicates:
        print("\n❌ Execution Halting: The same file content exists in more than one place inside Sorted/:")
        for file_hash, paths in duplicates.items():
            print(f"\n   Duplicate content ({file_hash[:12]}...):")
            for path in paths:
                print(f"     - {path}")
        print("\n   Resolve these duplicates by hand (keep only one copy) and run this again.")
        print("   Nothing has been changed.\n")
        sys.exit(1)

    print("🔎 Hashing Original/ ...")
    original_entries = hash_files_in(original_path)

    # hash -> the one path used to annotate the exclusion ledger entry.
    # Sorted wins when a hash exists in both, since that's where the file
    # actually ended up; Original is only a fallback for files dropped
    # during curation (see the README for why that still counts as "handled").
    sorted_hash_to_path = {file_hash: rel_path for rel_path, file_hash in sorted_entries.items()}
    original_hash_to_path = {}
    for rel_path, file_hash in original_entries.items():
        original_hash_to_path.setdefault(file_hash, rel_path)

    handled_hashes = set(sorted_entries.values()) | set(original_entries.values())

    registry_path = os.path.join(dropzone_path, REGISTRY_FILENAME)
    exclusion_list_path = os.path.join(dropzone_path, EXCLUDE_FILENAME)

    # hash -> every Dropzone-relative path registered under it (usually one,
    # but two identical files dumped together in the same run can share a
    # hash - if the content is handled, every physical copy gets archived).
    registry_by_hash = defaultdict(list)
    for file_hash, rel_path in read_checksum_pairs(registry_path):
        registry_by_hash[file_hash].append(rel_path)

    existing_exclusion_hashes = {file_hash for file_hash, _ in read_checksum_pairs(exclusion_list_path)}

    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    current_batch_excluded_dir = os.path.join(excluded_root_dir, f"curation_{timestamp}")

    files_to_move = []
    remaining_registry_records = []
    new_exclusion_records = []

    for file_hash, dropzone_paths in registry_by_hash.items():
        if file_hash in handled_hashes:
            for rel_path in dropzone_paths:
                files_to_move.append((os.path.join(dropzone_path, rel_path), rel_path))
            if file_hash not in existing_exclusion_hashes:
                annotated_path = sorted_hash_to_path.get(file_hash) or original_hash_to_path.get(file_hash)
                new_exclusion_records.append((file_hash, annotated_path))
        else:
            for rel_path in dropzone_paths:
                remaining_registry_records.append((file_hash, rel_path))

    print("\n🚚 Files matched by this curation session:")
    moved_count = 0
    for source_full_path, rel_path in files_to_move:
        if not os.path.exists(source_full_path):
            print(f"   [SKIP - MISSING] {rel_path}")
            continue
        destination_path = os.path.join(current_batch_excluded_dir, rel_path)
        if is_dry_run:
            print(f"   [WILL MOVE] Dropzone/{rel_path} -> Excluded/curation_{timestamp}/{rel_path}")
        else:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.move(source_full_path, destination_path)
            print(f"   [MOVED] -> {rel_path}")
        moved_count += 1

    if not is_dry_run:
        write_checksum_pairs(
            registry_path,
            remaining_registry_records,
            f"ACTIVE DROPZONE REGISTRY - UPDATED ON {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        )
        if new_exclusion_records:
            try:
                with open(exclusion_list_path, "a", encoding="utf-8") as f:
                    for file_hash, rel_path in new_exclusion_records:
                        f.write(f"{file_hash}\t{rel_path}\n")
            except (IOError, OSError) as e:
                print(f"❌ Critical Failure: Could not update {EXCLUDE_FILENAME}: {e}")

    print("\n" + "=" * 70)
    if is_dry_run:
        print(" SAFELY COMPLETED DRY-RUN PREVIEW (NO FILES MODIFIED)")
    else:
        print(" CURATION FINALIZATION COMPLETE")
    print("=" * 70)
    print(f" Files matched in this session           : {moved_count}")
    print(f" New entries added to {EXCLUDE_FILENAME:<17}: {len(new_exclusion_records)}")
    print(f" Remaining entries in Dropzone registry   : {len(remaining_registry_records)}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
