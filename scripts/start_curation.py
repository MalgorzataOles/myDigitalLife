#!/usr/bin/env python3
import os
import sys
import hashlib

# ==============================================================================
# CONFIGURATION PROPERTIES
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
    # Accept the path to the workspace folder that you manually prepared
    if len(sys.argv) > 1:
        curated_folder_path = sys.argv[1]
    else:
        print("❌ Execution Error: Missing required folder path argument.")
        print("Usage: python3 start_curation.py /path/to/Workspace/Your_Folder_Name")
        sys.exit(1)

    # Validation: Ensure the targeted directory physically exists on your drive
    if not os.path.exists(curated_folder_path) or not os.path.isdir(curated_folder_path):
        print(f"❌ Execution Halting: The specified folder path does not exist:\n   '{curated_folder_path}'")
        sys.exit(1)

    manifest_path = os.path.join(curated_folder_path, MANIFEST_FILENAME)

    # Safety constraint: Do not overwrite an existing manifest file
    if os.path.exists(manifest_path):
        print(f"❌ Safety Halt: A '{MANIFEST_FILENAME}' already exists inside this folder.")
        print("   To protect your existing tracking data, this script will not overwrite it.")
        sys.exit(1)

    # Casual, human-friendly home print template
    print("\n" + "~" * 60)
    print(" 📸 INITIALIZING BASELINE CURATION MANIFEST...")
    print("~" * 60)
    print(f" Target folder   : {curated_folder_path}")
    print(f" Output manifest : {manifest_path}")
    print("~" * 60 + "\n")

    manifest_entries = []
    print("🔎 Scanning files to generate baseline fingerprints...")

    # Walk through the manually prepared folder to extract unmutated signatures
    for root, _, files in os.walk(curated_folder_path):
        for file in files:
            # Skip hidden metadata components or the local registration file if it exists
            if file.startswith("._") or file == ".DS_Store" or file.endswith(".registered.sha256"):
                continue
                
            full_path = os.path.join(root, file)
            
            # Map path name relative to the curated folder root
            relative_path = os.path.relpath(full_path, curated_folder_path)
            
            file_hash = calculate_sha256(full_path)
            if file_hash:
                print(f"   [SNAPSHOT LOGGED] {relative_path}")
                manifest_entries.append((file_hash, relative_path))

    # Write the compiled entries into your flat plain text session.manifest
    if manifest_entries:
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("# --- ORIGINAL BASELINE CURATION SESSION MANIFEST ---\n")
                for file_hash, rel_path in manifest_entries:
                    f.write(f"{file_hash}\t{rel_path}\n")
                    
            print("\n" + "=" * 70)
            print(" MANIFEST INITIALIZATION COMPLETE")
            print("=" * 70)
            print(f" Total files registered in manifest : {len(manifest_entries)}")
            print(f" 📂 Ready for curation inside      : {curated_folder_path}")
            print("=" * 70 + "\n")
        except (IOError, OSError) as e:
            print(f"❌ Critical Failure: Could not write manifest file to disk: {e}")
    else:
        print("⚠️  Warning: No valid unique files were found in this folder to track.")

if __name__ == "__main__":
    main()