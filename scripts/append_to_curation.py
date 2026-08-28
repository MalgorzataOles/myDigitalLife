#!/usr/bin/env python3
import os
import sys
import hashlib
from datetime import datetime

# ==============================================================================
# CONFIGURATION
# ==============================================================================
MANIFEST_FILENAME = "session.manifest"

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

def main():
    # Accept the specific 'appended' folder path as a command line argument
    if len(sys.argv) > 1:
        appended_folder_path = sys.argv[1]
    else:
        print("❌ Execution Error: Missing required path argument.")
        print("Usage: python3 append_to_curation.py /path/to/curated_folder/appended")
        sys.exit(1)

    # Validation: Ensure the targeted subfolder physically exists
    if not os.path.exists(appended_folder_path) or not os.path.isdir(appended_folder_path):
        print(f"❌ Execution Halting: The specified folder path does not exist:\n   '{appended_folder_path}'")
        sys.exit(1)

    # Resolution: Find the parent directory and locate the session.manifest file
    curated_root_dir = os.path.dirname(os.path.normpath(appended_folder_path))
    manifest_path = os.path.join(curated_root_dir, MANIFEST_FILENAME)

    if not os.path.exists(manifest_path):
        print(f"❌ Execution Halting: No '{MANIFEST_FILENAME}' found in the parent directory.")
        print(f"   The specified folder must be inside an already registered curation folder.")
        sys.exit(1)

    # Casual, human-friendly home print template
    print("\n" + "~" * 60)
    print(" 📂 APPENDING NEW ADDITIONS TO ACTIVE MANIFEST...")
    print("~" * 60)
    print(f" Processing folder : {appended_folder_path}")
    print(f" Target manifest   : {manifest_path}")
    print("~" * 60 + "\n")

    new_manifest_entries = []

    print("🔎 Scanning your appended files folder...")
    
    for root, _, files in os.walk(appended_folder_path):
        for file in files:
            # Skip hidden operating system metadata files
            if file.startswith("._") or file == ".DS_Store":
                continue
                
            full_path = os.path.join(root, file)
            
            # Calculate the current file hash BEFORE any curation modifications happen
            file_hash = calculate_sha256(full_path)
            if not file_hash:
                continue

            # CRUCIAL ROOT MAPPING: Map the file path relative to the Dropzone
            # This allows the finalizer script to locate and delete the original copy later
            relative_to_curated = os.path.relpath(full_path, curated_root_dir)
            
            print(f"   [LOGGED] Registering signature -> {relative_to_curated}")
            new_manifest_entries.append((file_hash, relative_to_curated))

    # Append the new records cleanly to the manifest file using tab separation
    if new_manifest_entries:
        # Make manifest temporarily writable (it's protected as read-only by start_curation.py)
        try:
            os.chmod(manifest_path, 0o644)
        except OSError as e:
            print(f"⚠️  Warning: Could not make manifest writable: {e}")
        
        try:
            # Open file in append ("a") mode to protect your existing session data
            with open(manifest_path, "a", encoding="utf-8") as f:
                # Add a clear comment line to separate batches within the manifest file text
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n# --- APPENDED BATCH: {timestamp} ---\n")
                
                for file_hash, rel_path in new_manifest_entries:
                    f.write(f"{file_hash}\t{rel_path}\n")
            
            # Restore read-only protection
            os.chmod(manifest_path, 0o444)
                    
            print("\n" + "=" * 70)
            print(" APPEND RUN COMPLETE")
            print("=" * 70)
            print(f" New entries added to manifest : {len(new_manifest_entries)}")
            print("=" * 70 + "\n")
        except (IOError, OSError) as e:
            # Attempt to restore read-only protection even on failure
            try:
                os.chmod(manifest_path, 0o444)
            except OSError:
                print(f"⚠️  Warning: Manifest left writable - could not restore read-only: {e}")
            print(f"❌ Critical Failure: Could not write updates to manifest file: {e}")
    else:
        print("\n" + "✅" + "-" * 68)
        print(" Task Complete: No new files found to add inside the folder.")
        print("-" * 70)

if __name__ == "__main__":
    main()