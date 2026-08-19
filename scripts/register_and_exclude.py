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

def load_checksum_list(file_path: str, is_local_registry: bool = False) -> set:
    """
    Reads a tab-separated checksum file.
    If parsing the exclusion list, returns a set of hashes (index 0).
    If parsing the local registry, returns a set of tracked relative paths (index 1).
    """
    extracted_data = set()
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        extracted_data.add(parts[1] if is_local_registry else parts[0])
                    elif len(parts) == 1 and not is_local_registry:
                        extracted_data.add(parts[0])
        except (IOError, OSError) as e:
            print(f"⚠️  Warning: Error reading tracker file {file_path}: {e}")
    return extracted_data

def main():
    config = load_configuration()
    
    # Target path resolution: Accepts command line folder path argument first
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = config.get("dropzone_path")

    excluded_root_dir = config.get("excluded_path")

    if not target_dir or not os.path.exists(target_dir):
        print(f"❌ Execution Halting: Target path invalid or inaccessible:\n   '{target_dir}'")
        sys.exit(1)

    if not excluded_root_dir:
        print("❌ Execution Halting: 'excluded_path' configuration is completely missing from config.json.")
        sys.exit(1)

    # DYNAMIC NAMING GENERATION based on processed folder name
    folder_name = os.path.basename(os.path.normpath(target_dir))
    
    local_db_filename = f"{folder_name}.registered.sha256"
    local_db_path = os.path.join(target_dir, local_db_filename)
    
    exclusion_filename = f"{folder_name}.excluded.sha256"
    exclusion_list_path = os.path.join(target_dir, exclusion_filename)

    # Pre-load datasets into memory securely before header generation
    exclusion_set = load_checksum_list(exclusion_list_path, is_local_registry=False)
    local_tracked_paths = load_checksum_list(local_db_path, is_local_registry=True)

    # Dynamic creation of the timestamped isolation folder inside .Excluded/<source_folder>/
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_batch_excluded_dir = os.path.join(excluded_root_dir, folder_name, timestamp)

    # Clean, literal startup dashboard
    print("\n" + "~" * 60)
    print(" 📸 STARTING RUN: Checking for new files...")
    print("~" * 60)
    print(f" Scanning folder   : {target_dir}")
    print(f" Registry file     : {local_db_filename}")
    #  add the exclusion file line if it exists
    if os.path.exists(exclusion_list_path) and len(exclusion_set) > 0:
        print(f" Exclusion file    : {exclusion_filename} ({len(exclusion_set)} items loaded)")
    print("~" * 60 + "\n")

    new_entries = []
    excluded_files_log = []

    print("🔎 Scanning files ...")
    
    for root, _, files in os.walk(target_dir):
        for file in files:
            # Skip hidden metadata artifacts and the registry files themselves
            if (file.startswith("._") or 
                file == ".DS_Store" or 
                file == local_db_filename or 
                file == exclusion_filename):
                continue
                
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, target_dir)

            # Case A: Already logged locally, skip configuration check
            if relative_path in local_tracked_paths:
                continue

            # Case B: Brand new file. Calculate signature
            file_hash = calculate_sha256(full_path)
            if not file_hash:
                continue

            # Case C: If found in dynamic exclusions list, stage for structured migration
            if file_hash in exclusion_set:
                excluded_files_log.append((full_path, relative_path))
            else:
                # Case D: Safe unique file. Stage to write to local directory registry
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

    # Save and commit new unique additions to local folder registry
    if new_entries:
        try:
            with open(local_db_path, "a", encoding="utf-8") as f:
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
        print(f"     (NOT back to {folder_name}/)")
        print("  3. Delete files when reviewed")
        print("  4. Session complete when .Excluded is empty")
        print("=" * 70 + "\n")
    else:
        print("=" * 70 + "\n")

if __name__ == "__main__":
    main()