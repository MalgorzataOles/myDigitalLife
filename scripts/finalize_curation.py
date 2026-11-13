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
    read_checksum_rows,
    load_checksum_list,
    find_unregistered_files,
    describe_folder_counts,
    folders_that_become_empty,
    remove_folders,
    hash_files_in,
    write_checksum_pairs,
    append_checksum_lines,
    check_folder_layout,
    get_user_name,
    get_log_path,
    run_log,
    normalize_path,
    pipeline_lock,
    TIMESTAMP_FORMAT,
    REGISTRY_FILENAME,
    EXCLUDE_FILENAME,
)

ORIGINAL_DIRNAME = "Original"
SORTED_DIRNAME = "Sorted"


def find_duplicate_hashes(entries: dict) -> dict:
    """Given {relative_path: hash}, returns {hash: [relative_paths]} for hashes seen more than once."""
    by_hash = defaultdict(list)
    for rel_path, file_hash in entries.items():
        by_hash[file_hash].append(rel_path)
    return {file_hash: paths for file_hash, paths in by_hash.items() if len(paths) > 1}


def main():
    args = sys.argv[1:]
    wants_dry_run = "--dry-run" in args
    wants_commit = "--commit" in args
    unknown_options = [arg for arg in args if arg.startswith("--") and arg not in ("--dry-run", "--commit")]
    paths = [arg for arg in args if not arg.startswith("--")]

    problem = None
    if unknown_options:
        problem = f"Unknown option: {' '.join(unknown_options)}"
    elif wants_dry_run and wants_commit:
        problem = "Use either --dry-run or --commit, not both."
    elif not paths and not (wants_dry_run or wants_commit):
        problem = "Missing the path to the curated session folder and the mode (--dry-run or --commit)."
    elif not paths:
        problem = "Missing the path to the curated session folder (the Name_Date folder inside Workspace)."
    elif len(paths) > 1:
        problem = (f"Expected one folder path but got {len(paths)}: {' | '.join(paths)}\n"
                   "   If the path contains spaces, put it in quotes.")
    elif not (wants_dry_run or wants_commit):
        problem = "Missing the mode: add --dry-run (preview only) or --commit (do it for real)."

    if problem:
        print(f"❌ Execution Error: {problem}")
        print("   Nothing has been changed.")
        print("")
        print("Usage (choose one):")
        print("  Preview only, changes nothing : python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date --dry-run")
        print("  Do it for real                : python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date --commit")
        sys.exit(1)

    config = load_configuration()
    user_name = get_user_name(config)
    log_path = get_log_path(config)

    with run_log(log_path, "finalize_curation.py", user_name, sys.argv[1:]):
        run(wants_dry_run, paths[0], config, user_name)


def run(is_dry_run, session_path, config, user_name):
    original_path = os.path.join(session_path, ORIGINAL_DIRNAME)
    sorted_path = os.path.join(session_path, SORTED_DIRNAME)

    if not os.path.isdir(original_path):
        print(f"❌ Execution Halting: No '{ORIGINAL_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)
    if not os.path.isdir(sorted_path):
        print(f"❌ Execution Halting: No '{SORTED_DIRNAME}/' folder found inside:\n   '{session_path}'")
        sys.exit(1)

    dropzone_path = config.get("dropzone_path")
    excluded_root_dir = config.get("excluded_path")

    if not dropzone_path or not os.path.exists(dropzone_path):
        print(f"❌ Execution Halting: 'dropzone_path' is invalid or inaccessible:\n   '{dropzone_path}'")
        sys.exit(1)
    if not excluded_root_dir:
        print("❌ Execution Halting: 'excluded_path' configuration is missing from config.json.")
        sys.exit(1)

    layout_problem = check_folder_layout(dropzone_path, excluded_root_dir, session_path, config.get("log_path"))
    if layout_problem:
        print(f"❌ Execution Halting: {layout_problem}")
        sys.exit(1)

    with pipeline_lock(dropzone_path, "finalize_curation.py"):
        process(is_dry_run, session_path, original_path, sorted_path, dropzone_path, excluded_root_dir, user_name)


def process(is_dry_run, session_path, original_path, sorted_path, dropzone_path, excluded_root_dir, user_name):
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

    # Step 0a: finalizing only archives files listed in the registry, so a
    # Dropzone file that was never registered would silently be left behind.
    registry_path = os.path.join(dropzone_path, REGISTRY_FILENAME)
    unregistered = find_unregistered_files(
        dropzone_path, load_checksum_list(registry_path, is_local_registry=True)
    )
    if unregistered:
        print("❌ Execution Halting: These Dropzone folders contain files that are not registered yet:")
        for line in describe_folder_counts(unregistered):
            print(f"     - {line}")
        print("\n   Run register_and_exclude.py first, then run this again.")
        print("   Nothing has been changed.\n")
        sys.exit(1)

    # Step 0b: refuse to continue if the same content was filed into two
    # different places inside Sorted/ - we have no way to know which final
    # path is the "real" one.
    print("🔎 Hashing Sorted/ ...")
    unreadable = []
    sorted_entries = hash_files_in(sorted_path, unreadable)
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
    original_entries = hash_files_in(original_path, unreadable)

    # A file we could not read would silently count as "not handled", so
    # stop instead of finalizing a session we only partly understand.
    if unreadable:
        print("\n❌ Execution Halting: These files in Original/ or Sorted/ could not be read:")
        for rel_path in sorted(unreadable):
            print(f"     - {rel_path}")
        print("\n   Fix the problem (or remove the files) and run this again.")
        print("   Nothing has been changed.\n")
        sys.exit(1)

    # hash -> the one path used to annotate the exclusion ledger entry.
    # Sorted wins when a hash exists in both, since that's where the file
    # actually ended up; Original is only a fallback for files dropped
    # during curation (see the README for why that still counts as "handled").
    sorted_hash_to_path = {file_hash: rel_path for rel_path, file_hash in sorted_entries.items()}
    original_hash_to_path = {}
    for rel_path, file_hash in original_entries.items():
        original_hash_to_path.setdefault(file_hash, rel_path)

    handled_hashes = set(sorted_entries.values()) | set(original_entries.values())

    exclusion_list_path = os.path.join(dropzone_path, EXCLUDE_FILENAME)

    # hash -> every Dropzone-relative path registered under it (usually one,
    # but two identical files dumped together in the same run can share a
    # hash - if the content is handled, every physical copy gets archived).
    registry_by_hash = defaultdict(list)
    for file_hash, rel_path, *extra_columns in read_checksum_rows(registry_path):
        registry_by_hash[file_hash].append((rel_path, tuple(extra_columns)))

    existing_exclusion_hashes = {file_hash for file_hash, _ in read_checksum_pairs(exclusion_list_path)}

    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    current_batch_excluded_dir = os.path.join(excluded_root_dir, f"curation_{timestamp}")

    files_to_move = []
    remaining_registry_records = []
    new_exclusion_records = []

    for file_hash, dropzone_paths in registry_by_hash.items():
        if file_hash in handled_hashes:
            for rel_path, _ in dropzone_paths:
                files_to_move.append((os.path.join(dropzone_path, rel_path), rel_path))
            if file_hash not in existing_exclusion_hashes:
                annotated_path = sorted_hash_to_path.get(file_hash) or original_hash_to_path.get(file_hash)
                new_exclusion_records.append((file_hash, annotated_path))
        else:
            for rel_path, extra_columns in dropzone_paths:
                remaining_registry_records.append((file_hash, rel_path, *extra_columns))

    # Files in Original/ that Dropzone does not know are still "curated after
    # all": their hashes go into the ledger so the same content is caught if it
    # is ever dumped into Dropzone later. Often they are harmless (they came
    # from somewhere else), but a changed copy of a Dropzone file looks exactly
    # the same, and its untouched original then stays in Dropzone. So list them,
    # and point out ones whose name matches a Dropzone file that is left over.
    registry_hashes = set(registry_by_hash)
    unmatched_original = sorted(
        rel_path for rel_path, file_hash in original_entries.items() if file_hash not in registry_hashes
    )
    leftover_names = defaultdict(list)
    for file_hash, dropzone_paths in registry_by_hash.items():
        if file_hash not in handled_hashes:
            for rel_path, _ in dropzone_paths:
                leftover_names[normalize_path(os.path.basename(rel_path)).casefold()].append(rel_path)

    pending_hashes = {file_hash for file_hash, _ in new_exclusion_records}
    original_only_records = []
    for file_hash in sorted({original_entries[rel_path] for rel_path in unmatched_original}):
        if file_hash not in existing_exclusion_hashes and file_hash not in pending_hashes:
            annotated_path = sorted_hash_to_path.get(file_hash) or original_hash_to_path.get(file_hash)
            original_only_records.append((file_hash, annotated_path))
    new_exclusion_records += original_only_records

    # Order matters for safe re-runs after an interruption: record the ledger
    # first, move files second, and rewrite the registry last. Whatever stage
    # was interrupted, running this again completes the remaining stages.
    if not is_dry_run and new_exclusion_records:
        try:
            append_checksum_lines(
                exclusion_list_path,
                [f"{file_hash}\t{rel_path}\t{timestamp}\t{user_name}" for file_hash, rel_path in new_exclusion_records],
            )
        except OSError as e:
            print(f"❌ Critical Failure: Could not update {EXCLUDE_FILENAME}: {e}")
            print("   Nothing has been moved. Run this again.")
            sys.exit(1)

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
            try:
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.move(source_full_path, destination_path)
            except OSError as e:
                print(f"   ❌ Could not move {rel_path}: {e}")
                print("\n   Stopped. The files moved so far are safe in Excluded/.")
                print("   Fix the problem and run this again - it picks up where it stopped.")
                sys.exit(1)
            print(f"   [MOVED] -> {rel_path}")
        moved_count += 1

    # Folders emptied by this session (the <source> folder such as Phone1 is kept).
    # Done before the registry rewrite so a re-run after an interruption still
    # knows which folders to look at; files already moved count as gone.
    emptied_folders = folders_that_become_empty(dropzone_path, [rel for _, rel in files_to_move])
    if emptied_folders:
        print("\n🧹 Dropzone folders left empty by this session:")
        for rel_folder in emptied_folders:
            print(f"   [{'WILL REMOVE' if is_dry_run else 'REMOVED'}] {rel_folder}{os.sep}")
        if not is_dry_run:
            remove_folders(dropzone_path, emptied_folders)

    if not is_dry_run:
        if not write_checksum_pairs(
            registry_path,
            remaining_registry_records,
            f"DROPZONE REGISTRY - UPDATED ON {datetime.now().strftime(TIMESTAMP_FORMAT)}",
        ):
            print("   The files were moved, but the registry was not updated. Run this again.")
            sys.exit(1)

    if unmatched_original:
        print("\n⚠️  Files in Original/ that are not in the Dropzone registry:")
        for rel_path in unmatched_original:
            print(f"   - {rel_path}")
            lookalikes = leftover_names.get(normalize_path(os.path.basename(rel_path)).casefold())
            if lookalikes:
                print(f"       possibly a changed copy of Dropzone/{lookalikes[0]}"
                      f"{' (and others)' if len(lookalikes) > 1 else ''}, which stays in Dropzone")
        if is_dry_run:
            print(f"   Their content WILL BE recorded in {EXCLUDE_FILENAME} when you run with --commit.")
        else:
            print(f"   Their content was recorded in {EXCLUDE_FILENAME}.")
        print("   If a file was changed by mistake, put the untouched copy from Dropzone back")
        print("   into Original/ and run this again before using --commit.")

    print("\n" + "=" * 70)
    if is_dry_run:
        print(" DRY-RUN ONLY: NOTHING WAS CHANGED, THE CURATION IS NOT FINALIZED YET")
        print(" Run again with --commit to apply the changes listed above.")
    else:
        print(" CURATION FINALIZATION COMPLETE")
    print("=" * 70)
    print(f" Files matched in this session           : {moved_count}")
    print(f" New entries added to {EXCLUDE_FILENAME:<17}: {len(new_exclusion_records)}")
    print(f" Original/ files not in Dropzone          : {len(unmatched_original)}")
    print(f" Remaining entries in Dropzone registry   : {len(remaining_registry_records)}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
