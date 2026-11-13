#!/usr/bin/env python3
import os
import sys
import json
import json
import shutil
import signal
import socket
import getpass
import hashlib
import unicodedata
from contextlib import contextmanager
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE_PATH = os.path.join(REPO_ROOT, "config.json")

# Shared by register_and_exclude.py and finalize_curation.py so the two
# scripts can never silently drift onto different names for the same file.
REGISTRY_FILENAME = "registered.sha256"
EXCLUDE_FILENAME = "exclude.sha256"

# Folder created in Dropzone while register_and_exclude.py or finalize_curation.py
# runs, so two people can't change the registry at the same time.
LOCK_DIRNAME = ".pipeline.lock"
LOCK_OWNER_FILENAME = "owner.json"

# One timestamp format for batch folder names and registry rows (YYYYMMDD_hhmmss).
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


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


def read_checksum_pairs(file_path: str) -> list:
    """Reads a tab-separated checksum file, keeping every (hash, path) pair as-is."""
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
                        records.append((parts[0], parts[1]))
        except (IOError, OSError) as e:
            print(f"⚠️  Warning: Error reading file {file_path}: {e}")
    return records


def read_checksum_rows(file_path: str) -> list:
    """Reads a tab-separated checksum file, keeping every column of every data row."""
    rows = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    cleaned = line.strip()
                    if not cleaned or cleaned.startswith("#"):
                        continue
                    parts = cleaned.split("\t")
                    if len(parts) >= 2:
                        rows.append(tuple(parts))
        except (IOError, OSError) as e:
            print(f"⚠️  Warning: Error reading file {file_path}: {e}")
    return rows


def is_ignored_file(filename: str) -> bool:
    """OS metadata files (macOS and Windows) that are never part of the collection."""
    return (filename.startswith("._") or
            filename in (".DS_Store", "Thumbs.db", "desktop.ini"))


def normalize_path(path: str) -> str:
    """Unicode-normalizes a path (NFC) so 'ü' typed two different ways compares equal."""
    return unicodedata.normalize("NFC", path)


def has_unsupported_name(relative_path: str) -> bool:
    """Tabs and line breaks would corrupt the tab-separated registry rows."""
    return any(char in relative_path for char in ("\t", "\n", "\r"))


def check_folder_layout(dropzone_path: str, excluded_path: str, session_path: str = None):
    """
    Returns an error message if the folders overlap in a way that would make the
    scripts treat their own output as new files, otherwise None.
    """
    def is_inside(child: str, parent: str) -> bool:
        child, parent = os.path.realpath(child), os.path.realpath(parent)
        return child == parent or os.path.commonpath([child, parent]) == parent

    if is_inside(excluded_path, dropzone_path):
        return "'excluded_path' must not be inside (or the same as) 'dropzone_path'."
    if is_inside(dropzone_path, excluded_path):
        return "'dropzone_path' must not be inside (or the same as) 'excluded_path'."
    if session_path and is_inside(session_path, dropzone_path):
        return "The session folder must not be inside the Dropzone."
    return None


def write_checksum_pairs(file_path: str, records: list, header_text: str) -> bool:
    """
    Replaces a checksum file in one step, so an interruption never leaves it
    half-written. Each record is a tuple of columns. Returns True on success.
    """
    temp_path = f"{file_path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(f"# {header_text}\n")
            for record in records:
                f.write("\t".join(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)
        return True
    except (IOError, OSError) as e:
        print(f"❌ Critical Failure: Could not write updates to {file_path}: {e}")
        return False


def append_checksum_lines(file_path: str, lines: list) -> None:
    """
    Appends lines to a ledger file. If an earlier run was cut off in the middle
    of a line, first ends that line so the new entries don't get glued onto it.
    Raises OSError if the file cannot be written.
    """
    needs_newline = False
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) != b"\n"
    with open(file_path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        for line in lines:
            f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def is_ignored_dropzone_file(filename: str) -> bool:
    """Files in Dropzone that are never registered: OS metadata and our own ledgers."""
    return (is_ignored_file(filename) or
            filename == REGISTRY_FILENAME or
            filename == REGISTRY_FILENAME + ".tmp" or
            filename == EXCLUDE_FILENAME)


def _process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _read_lock_owner(lock_path: str) -> dict:
    try:
        with open(os.path.join(lock_path, LOCK_OWNER_FILENAME), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _lock_is_stale(owner: dict) -> bool:
    """A lock is only known to be stale when it was made on this computer by a process that is gone."""
    return (owner.get("host") == socket.gethostname()
            and isinstance(owner.get("pid"), int)
            and not _process_is_running(owner["pid"]))


@contextmanager
def pipeline_lock(dropzone_path: str, script_name: str):
    """
    Holds an exclusive lock on the Dropzone for the duration of the with-block.
    Creating a folder is atomic, even on a network share, so only one run can
    succeed. The lock is released on normal exit, errors, Ctrl-C and when the
    terminal is closed. After a hard crash a stale lock may remain: one left by
    a dead process on this computer is removed automatically, any other is
    reported with who made it and how to remove it.
    """
    lock_path = os.path.join(dropzone_path, LOCK_DIRNAME)

    for attempt in (1, 2):
        try:
            os.mkdir(lock_path)
            break
        except FileExistsError:
            owner = _read_lock_owner(lock_path)
            if attempt == 1 and _lock_is_stale(owner):
                print("⚠️  Removing a leftover lock from an earlier run that did not finish.")
                shutil.rmtree(lock_path, ignore_errors=True)
                continue
            who = (f"{owner.get('script', 'a script')}, started {owner.get('started', '?')} "
                   f"by {owner.get('user', '?')} on {owner.get('host', '?')}") if owner else "unknown (it may just be starting)"
            print("❌ Execution Halting: another run is in progress on this Dropzone:")
            print(f"   {who}")
            print("\n   Wait for it to finish, then run this again.")
            print(f"   If you are SURE that run crashed and nobody is running these scripts,")
            print(f"   delete this folder and run again:\n     {lock_path}")
            sys.exit(1)

    try:
        user = getpass.getuser()
    except Exception:
        user = "?"
    owner_info = {"script": script_name, "user": user, "host": socket.gethostname(),
                  "pid": os.getpid(), "started": datetime.now().strftime(TIMESTAMP_FORMAT)}

    previous_handlers = {}

    def _exit_cleanly(signum, frame):
        sys.exit(128 + signum)

    try:
        with open(os.path.join(lock_path, LOCK_OWNER_FILENAME), "w", encoding="utf-8") as f:
            json.dump(owner_info, f)
        for name in ("SIGTERM", "SIGHUP"):
            if hasattr(signal, name):
                previous_handlers[getattr(signal, name)] = signal.signal(getattr(signal, name), _exit_cleanly)
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        shutil.rmtree(lock_path, ignore_errors=True)


def find_unregistered_files(dropzone_path: str, registered_paths: set) -> list:
    """Returns the sorted Dropzone-relative paths of files not yet listed in the registry."""
    unregistered = []
    known_paths = {normalize_path(path) for path in registered_paths}
    for root, dirs, files in os.walk(dropzone_path):
        dirs[:] = [d for d in dirs if d != LOCK_DIRNAME]
        for file in files:
            if is_ignored_dropzone_file(file):
                continue
            relative_path = os.path.relpath(os.path.join(root, file), dropzone_path)
            if normalize_path(relative_path) not in known_paths:
                unregistered.append(relative_path)
    return sorted(unregistered)


def group_by_source_folder(relative_paths: list, depth: int = 2) -> dict:
    """
    Groups Dropzone-relative paths by their first `depth` folders (the expected
    <source>/<date> layout) and returns {group_label: file_count}. A file with
    no parent folder is its own group, labelled by its file name.
    """
    groups = {}
    for rel_path in relative_paths:
        parts = rel_path.split(os.sep)
        folder_parts = parts[:-1][:depth]
        label = os.sep.join(folder_parts) + os.sep if folder_parts else rel_path
        groups[label] = groups.get(label, 0) + 1
    return dict(sorted(groups.items()))


def describe_folder_counts(relative_paths: list) -> list:
    """Returns display lines like 'Phone1/2026-09-20/  (432 files)', one per source folder."""
    return [
        f"{label}  ({count} file{'s' if count != 1 else ''})"
        for label, count in group_by_source_folder(relative_paths).items()
    ]


def hash_files_in(folder_path: str, unreadable: list = None) -> dict:
    """
    Walks a folder and returns {relative_path: hash} for every real file in it.
    Files that cannot be read are left out and, if a list is given, appended to it.
    """
    entries = {}
    for root, _, files in os.walk(folder_path):
        for file in files:
            if is_ignored_file(file):
                continue
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, folder_path)
            file_hash = calculate_sha256(full_path)
            if file_hash:
                entries[relative_path] = file_hash
            elif unreadable is not None:
                unreadable.append(relative_path)
    return entries
