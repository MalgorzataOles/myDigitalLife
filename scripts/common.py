#!/usr/bin/env python3
import os
import sys
import json
import re
import json
import shutil
import traceback
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

# Folder created in the state folder while register_and_exclude.py or
# finalize_curation.py runs, so two people can't change the registry at the same time.
LOCK_DIRNAME = ".pipeline.lock"
LOCK_OWNER_FILENAME = "owner.json"

# Value of "user_name" in config.json.template; it must be replaced by your own name.
PLACEHOLDER_USER_NAME = "CHANGE_ME"

# Value of "log_path" in config.json.template; it must be replaced by a real folder.
PLACEHOLDER_LOG_PATH = "/path/to/your/storage/Logs"

# Value of "state_path" in config.json.template; it must be replaced by a real folder.
PLACEHOLDER_STATE_PATH = "/path/to/your/storage/State"

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


def get_user_name(config: dict) -> str:
    """Returns the person's name from config.json, or stops if it was never filled in."""
    user_name = config.get("user_name")
    user_name = user_name.strip() if isinstance(user_name, str) else ""
    if not user_name or user_name == PLACEHOLDER_USER_NAME:
        print("❌ Execution Halting: 'user_name' in config.json is missing or still the placeholder.")
        print(f"   Open {CONFIG_FILE_PATH} and set \"user_name\" to your own name, for example \"Gosia\".")
        sys.exit(1)
    if any(char in user_name for char in ("\t", "\n", "\r")):
        print("❌ Execution Halting: 'user_name' in config.json must not contain tabs or line breaks.")
        sys.exit(1)
    return user_name


def get_state_path(config: dict) -> str:
    """Returns the folder holding the registry, the ledger and the lock, or stops if it was never filled in."""
    state_path = config.get("state_path")
    state_path = state_path.strip() if isinstance(state_path, str) else ""
    if not state_path or state_path == PLACEHOLDER_STATE_PATH:
        print("❌ Execution Halting: 'state_path' in config.json is missing or still the placeholder.")
        print(f"   Open {CONFIG_FILE_PATH} and set \"state_path\" to the folder for registered.sha256,")
        print("   exclude.sha256 and the run lock (it must not be inside the Dropzone).")
        sys.exit(1)
    return state_path


def legacy_state_files_in_dropzone(dropzone_path: str) -> list:
    """Names of registry/ledger files still lying in the Dropzone from before they moved to state_path."""
    return [name for name in (REGISTRY_FILENAME, EXCLUDE_FILENAME, REGISTRY_FILENAME + ".tmp")
            if os.path.exists(os.path.join(dropzone_path, name))]


def get_log_path(config: dict) -> str:
    """Returns the shared log folder from config.json, or stops if it was never filled in."""
    log_path = config.get("log_path")
    log_path = log_path.strip() if isinstance(log_path, str) else ""
    if not log_path or log_path == PLACEHOLDER_LOG_PATH:
        print("❌ Execution Halting: 'log_path' in config.json is missing or still the placeholder.")
        print(f"   Open {CONFIG_FILE_PATH} and set \"log_path\" to the shared folder where run logs are kept.")
        sys.exit(1)
    return log_path


class _Tee:
    """Passes everything written to a terminal stream on to the log file as well."""

    def __init__(self, stream, log_file):
        self._stream = stream
        self._log_file = log_file
        self._log_failed = False

    def write(self, text):
        written = self._stream.write(text)
        if not self._log_failed:
            try:
                self._log_file.write(text)
                self._log_file.flush()
            except (OSError, ValueError):
                self._log_failed = True
                self._stream.write("\n⚠️  Writing to the log file failed; this run is no longer being logged.\n")
        return written

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextmanager
def run_log(log_path: str, script_name: str, user_name: str, args: list):
    """
    Writes everything the run prints to a new log file in log_path, with a header
    (who, when, which arguments) and a footer (how the run ended, including the
    full error if it crashed). Stops if the log file cannot be created, so no run
    goes unlogged.
    """
    started = datetime.now()
    safe_user = re.sub(r"[^A-Za-z0-9._-]", "_", user_name)
    base_name = f"{started.strftime(TIMESTAMP_FORMAT)}_{os.path.splitext(script_name)[0]}_{safe_user}"

    log_file, log_file_path = None, None
    try:
        os.makedirs(log_path, exist_ok=True)
        for counter in range(100):
            candidate = os.path.join(log_path, base_name + (f"_{counter}" if counter else "") + ".log")
            try:
                log_file = open(candidate, "x", encoding="utf-8")
                log_file_path = candidate
                break
            except FileExistsError:
                continue
    except OSError as e:
        print(f"❌ Execution Halting: Cannot write logs to 'log_path' ({log_path}): {e}")
        sys.exit(1)
    if log_file is None:
        print(f"❌ Execution Halting: Could not create a log file in {log_path}.")
        sys.exit(1)

    log_file.write(f"# script    : {script_name}\n# user      : {user_name}\n"
                   f"# computer  : {socket.gethostname()}\n"
                   f"# started   : {started.strftime(TIMESTAMP_FORMAT)}\n"
                   f"# arguments : {' '.join(args) if args else '(none)'}\n\n")
    log_file.flush()

    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Tee(original_stdout, log_file), _Tee(original_stderr, log_file)
    status = "finished normally"
    try:
        print(f"📝 Log file: {log_file_path}")
        yield
    except SystemExit as e:
        status = f"stopped with exit status {0 if e.code is None else e.code}"
        raise
    except KeyboardInterrupt:
        status = "interrupted (Ctrl-C)"
        raise
    except BaseException:
        status = "CRASHED"
        try:
            log_file.write("\n" + traceback.format_exc())
        except (OSError, ValueError):
            pass
        raise
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        try:
            log_file.write(f"\n# ended     : {datetime.now().strftime(TIMESTAMP_FORMAT)}\n# result    : {status}\n")
            log_file.close()
        except (OSError, ValueError):
            pass


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


def check_folder_layout(dropzone_path: str, excluded_path: str, session_path: str = None,
                        log_path: str = None, state_path: str = None):
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
    if log_path and is_inside(log_path, dropzone_path):
        return "'log_path' must not be inside the Dropzone."
    if state_path and is_inside(state_path, dropzone_path):
        return "'state_path' must not be inside the Dropzone."
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
    """Files in Dropzone that are never registered: OS metadata."""
    return is_ignored_file(filename)


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
def pipeline_lock(state_path: str, script_name: str):
    """
    Holds an exclusive lock on the state folder (and with it on the registry,
    the ledger and the Dropzone) for the duration of the with-block.
    Creating a folder is atomic, even on a network share, so only one run can
    succeed. The lock is released on normal exit, errors, Ctrl-C and when the
    terminal is closed. After a hard crash a stale lock may remain: one left by
    a dead process on this computer is removed automatically, any other is
    reported with who made it and how to remove it.
    """
    lock_path = os.path.join(state_path, LOCK_DIRNAME)

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
        for file in files:
            if is_ignored_dropzone_file(file):
                continue
            relative_path = os.path.relpath(os.path.join(root, file), dropzone_path)
            if normalize_path(relative_path) not in known_paths:
                unregistered.append(relative_path)
    return sorted(unregistered)


def folders_that_become_empty(dropzone_path: str, moved_relative_paths: list, keep_depth: int = 1) -> list:
    """
    Returns the Dropzone-relative folders that are (or will be) empty once the given
    files are gone, deepest first. Only the folders those files were in are considered.
    The top `keep_depth` levels (the <source> folder such as Phone1) are always kept,
    and so is the Dropzone itself. Hidden OS files (.DS_Store, ._*, ...) don't count
    as content.
    """
    moved_full_paths = {os.path.join(dropzone_path, rel_path) for rel_path in moved_relative_paths}
    candidates = set()
    for rel_path in moved_relative_paths:
        folder = os.path.dirname(rel_path)
        parts = [part for part in folder.split(os.sep) if part] if folder else []
        if ".." in parts:
            continue
        for depth in range(len(parts), keep_depth, -1):
            candidates.add(os.sep.join(parts[:depth]))

    removable, result = set(), []
    for rel_folder in sorted(candidates, key=lambda path: path.count(os.sep), reverse=True):
        folder = os.path.join(dropzone_path, rel_folder)
        if not os.path.isdir(folder) or os.path.islink(folder):
            continue
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        if all(
            (entry.is_dir(follow_symlinks=False) and entry.path in removable)
            or (not entry.is_dir(follow_symlinks=False)
                and (entry.path in moved_full_paths or is_ignored_file(entry.name)))
            for entry in entries
        ):
            removable.add(folder)
            result.append(rel_folder)
    return result


def remove_folders(dropzone_path: str, relative_folders: list) -> list:
    """Deletes the given (deepest first) folders, including leftover hidden OS files. Returns those removed."""
    removed = []
    for rel_folder in relative_folders:
        folder = os.path.join(dropzone_path, rel_folder)
        try:
            for entry in list(os.scandir(folder)):
                if not entry.is_dir(follow_symlinks=False) and is_ignored_file(entry.name):
                    os.remove(entry.path)
            os.rmdir(folder)
            removed.append(rel_folder)
        except OSError:
            pass
    return removed


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
