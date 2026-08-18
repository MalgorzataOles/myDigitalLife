#!/usr/bin/env python3
import os
import sys
import hashlib
import json
import shutil
from datetime import datetime

# ==============================================================================
# PATH RESOLUTION
# ==============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE_PATH = os.path.join(REPO_ROOT, "config.json")

MANIFEST_FILENAME = "session.manifest"
EXCLUSION_MASTER_FILENAME = "exclude.sha256"

def calculate_sha256(file_path: str) -> str:
    """Generates a secure SHA-256 fingerprint for a specified file."""
    hash_sha = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hash_sha.update(chunk)
        return hash_sha.hexdigest()
    except (IOError, OSError) as e:
        print(f"⚠️  Warning: Unable to read file {file_path}. Reason: {e}")
        return None

def load_configuration() -> dict:
    """Loads directory mappings from the root configuration file."""
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"❌ Initialization Error: Configuration missing at: '{CONFIG_FILE_PATH}'")
        sys.exit(1)
    try:
        with open(CONFIG_FILE_PATH, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Syntax Error in config.json: {e}")
        sys.exit(1)

def read_checksum_file_lines(file_path: str) -> list:
    """Reads a tab-separated checksum file line by line, preserving valid data pairs."""
    records = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    cleaned = line.strip()
                    if not cleaned or cleaned.startswith("#"):
                        continue
                    parts = cleaned.split("\t")
                    if len(parts) >= 2:
                        records.append((parts, parts[1]))
        except (IOError, OSError) as e:
            print(f"⚠️  Warning: Error reading file {file_path}: {e}")
    return records

def write_checksum_file_lines(file_path: str, records: list, header_text: str) -> None:
    """Writes or overwrites a checksum file cleanly using tab separation formatting."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {header_text}\n")
            for file_hash, rel_path in records:
                f.write(f"{file_hash}\t{rel_path}\n")
    except (IOError, OSError) as e:
        print(f"❌ Critical Failure: Could not write updates to {file_path}: {e}")

def main():
    config = load_configuration()
    
    # Parse input arguments and enforce safety flags
    is_dry_run = True
    curated_folder_path = None

    args = sys.argv[1:]
    if "--commit" in args:
        is_dry_run = False
        args.remove("--commit")

    if len(args) > 0:
        curated_folder_path = args[0]
    else:
        print("❌ Execution Error: Missing required folder path argument.")
        print("Usage (Dry-Run) : python3 finalize_curation.py /path/to/Workspace/Folder")
        print("Usage (Commit)  : python3 finalize_curation.py /path/to/Workspace/Folder --commit")
        sys.exit(1)

    # Validation checks
    if not os.path.exists(curated_folder_path) or not os.path.isdir(curated_folder_path):
        print(f"❌ Execution Halting: The specified folder path is invalid or missing:\n   '{curated_folder_path}'")
        sys.exit(1)

    dropzone_root = config.get("dropzone_path")
    cleared_root = config.get("cleared_path")

    if not dropzone_root or not os.path.exists(dropzone_root):
        print(f"❌ Execution Halting: 'dropzone_path' inside config.json is invalid or unreachable.")
        sys.exit(1)

    if not cleared_root:
        print(f"❌ Execution Halting: 'cleared_path' configuration is missing from config.json.")
        sys.exit(1)

    manifest_path = os.path.join(curated_folder_path, MANIFEST_FILENAME)
    if not os.path.exists(manifest_path):
        print(f"❌ Execution Halting: Missing required '{MANIFEST_FILENAME}' inside the curation folder.")
        sys.exit(1)

    # Resolve Dropzone naming structure dynamically
    dropzone_folder_name = os.path.basename(os.path.normpath(dropzone_root))
    dropzone_registry_path = os.path.join(dropzone_root, f"{dropzone_folder_name}.registered.sha256")

    if not os.path.exists(dropzone_registry_path):
        print(f"❌ Execution Halting: Cannot find the primary Dropzone registry file at:\n   '{dropzone_registry_path}'")
        sys.exit(1)

    master_exclusion_path = os.path.join(dropzone_root, "exclude.sha256")

    # Setup unique dated capsule targets
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_capsule_dir = os.path.join(cleared_root, timestamp)
    capsule_registry_name = f"{dropzone_folder_name}.registered.sha256"
    capsule_registry_path = os.path.join(current_capsule_dir, capsule_registry_name)

    # Casual, human-friendly home print header templates
    print("\n" + "~" * 60)
    if is_dry_run:
        print(" 👀 RUNNING IN DRY-RUN MODE: Previewing proposed steps safely...")
    else:
        print(" 📸 EXECUTING WORKSPACE CURATION FINALIZATION...")
    print("~" * 60)
    print(f" Curated Folder   : {curated_folder_path}")
    print(f" Dropzone Registry: {dropzone_registry_path}")
    print(f" Safety Capsule   : {current_capsule_dir}")
    print("~" * 60 + "\n")

    # Step 1: Read the session.manifest hashes to find what was pulled into curation
    manifest_records = read_checksum_file_lines(manifest_path)
    manifest_hashes_to_clear = {row[0] for row in manifest_records}

    # Step 2: Scan active Workspace folder to harvest finalized unique keepers
    current_workspace_hashes = set()
    print("🔎 Scanning curated folder to verify finalized contents...")
    for root, _, files in os.walk(curated_folder_path):
        for file in files:
            if file.startswith("._") or file == ".DS_Store" or file == MANIFEST_FILENAME:
                continue
            full_path = os.path.join(root, file)
            file_hash = calculate_sha256(full_path)
            if file_hash:
                current_workspace_hashes.add(file_hash)

    # Step 3: Read Dropzone primary registry file mapping layouts
    dropzone_registry_records = read_checksum_file_lines(dropzone_registry_path)

    # Step 4: Cross-reference datasets to build operation profiles
    files_to_shift = []
    removed_registry_rows = []
    updated_dropzone_registry_records = []

    for file_hash, rel_path in dropzone_registry_records:
        if file_hash in manifest_hashes_to_clear:
            full_source_path = os.path.join(dropzone_root, rel_path)
            full_dest_path = os.path.join(current_capsule_dir, rel_path)
            
            files_to_shift.append((full_source_path, full_dest_path, rel_path))
            removed_registry_rows.append((file_hash, rel_path))
        else:
            updated_dropzone_registry_records.append((file_hash, rel_path))

    # Step 5: Perform physical file transfers and structure mirroring
    moved_files_count = 0
    if files_to_shift:
        print("\n🚚 Processing original file transfers from Dropzone...")
        for src, dest, rel in files_to_shift:
            if os.path.exists(src):
                if is_dry_run:
                    print(f"   [WILL MOVE] Dropzone/{rel} -> Safety Capsule/{rel}")
                    moved_files_count += 1
                else:
                    try:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.move(src, dest)
                        print(f"   [MOVED TO CAPSULE] -> {rel}")
                        moved_files_count += 1
                    except OSError as e:
                        print(f"   ❌ Error moving file {rel}: {e}")
            else:
                if is_dry_run:
                    print(f"   [WILL SKIP] File missing from physical location -> {rel}")

    # Step 6: Commit registry maps and historical receipts
    if not is_dry_run:
        # Create capsule folder path if it wasn't made during movements
        if removed_registry_rows and not os.path.exists(current_capsule_dir):
            os.makedirs(current_capsule_dir, exist_ok=True)
            
        # Write individual receipts inside the date capsules
        if removed_registry_rows:
            write_checksum_file_lines(
                capsule_registry_path, 
                removed_registry_rows, 
                f"HISTORICAL CAPSULE RECEIPT - REMOVED ON {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
        # Commit cleanup changes to the main active Dropzone registry
        write_checksum_file_lines(
            dropzone_registry_path, 
            updated_dropzone_registry_records, 
            f"ACTIVE DROPZONE REGISTRY - UPDATED ON {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    # Step 7: Append workspace final keepers to master exclude list
    added_to_exclusion_count = 0
    if current_workspace_hashes:
        existing_master_records = read_checksum_file_lines(master_exclusion_path)
        existing_master_hashes = {row[0] for row in existing_master_records}
        
        if is_dry_run:
            for keeper_hash in current_workspace_hashes:
                if keeper_hash not in existing_master_hashes:
                    added_to_exclusion_count += 1
        else:
            try:
                with open(master_exclusion_path, "a", encoding="utf-8") as f:
                    for keeper_hash in current_workspace_hashes:
                        if keeper_hash not in existing_master_hashes:
                            f.write(f"{keeper_hash}\tPROCESSED_IN_WORKSPACE\n")
                            added_to_exclusion_count += 1
            except (IOError, OSError) as e:
                print(f"❌ Critical Failure: Could not write entries to master exclusion list: {e}")

    # Output clear final metrics block summary
    print("\n" + "=" * 70)
    if is_dry_run:
        print(" SAFELY COMPLETED DRY-RUN PREVIEW (NO FILES MODIFIED)")
    else:
        print(" CURATION BATCH FINALIZATION SUCCESSFUL")
    print("=" * 70)
    print(f" Files mapped for isolation movement     : {moved_files_count}")
    print(f" Entries to clear from Dropzone Registry : {len(removed_registry_rows)}")
    print(f" Remaining lines in Dropzone Registry    : {len(updated_dropzone_registry_records)}")
    print(f" New unique hashes to log to Exclude List: {added_to_exclusion_count}")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()