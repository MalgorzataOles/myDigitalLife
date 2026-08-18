# myDigitalLife

myDigitalLife automated data pipeline to safely register, filter, curate, and archive family media assets across local directories and QNAP network storage arrays.

## 📁 Repository & System Structure

### Git Repository Layout

```{text}
myDigitalLife/
  ├── .gitignore               # Excludes config.json and *.sha256 tracking files
  ├── config.json.template     # Template profile for required storage keys
  ├── config.json              # Local private path mappings (git-ignored)
  ├── scripts/
  │     ├── register_and_exclude.py
  │     ├── start_curation.py
  │     ├── append_to_curation.py
  │     └── finalize_curation.py
  └── tests/
        ├── __init__.py
        ├── test_register_and_exclude.py
        ├── test_start_curation.py
        ├── test_append_to_curation.py
        └── test_finalize_curation.py
```
  
### Connected Network Storage Array Layout

```{text}
/QNAP_Family_Vault/
  ├── Dropzone/   # Intake station for raw backups (holds local registry files)
  ├── Workspace/  # Active staging directory for manual sorting sessions
  ├── Excluded/   # Automatic duplicate catch basin (from register_and_exclude)
  └── Cleared/    # Safety vaults archiving files processed out of Dropzone
```

## 🔄 Core Pipeline Workflow

```{text}
Step 1: [Dropzone Intake] ──> (register_and_exclude.py) ──> Moves duplicates to [Excluded/]
                                     │ (Unique items logged)
                                     ▼
Step 2: [Manual Copy] ─────────> Copy event batches into [Workspace/]
                                     │
Step 3: [Curation Start] ──────> (start_curation.py) ───> Generates base snapshot manifest
                                     │
Step 4: [Additions Check] ─────> (append_to_curation.py) ──> Appends late Finder drags to manifest
                                     │
Step 5: [Finalization] ────────> (finalize_curation.py) ──> Archives Dropzone raw targets to [Cleared/]
                                                           Logs unique keepers to root exclude.sha256
```

## 💻 Script Execution & Commands

All scripts must be executed from the **root directory** of your repository.

Script | Purpose | When to Run | Command
-------| ------- | ----------- | -------
`register_and_exclude.py` | Registers fresh Dropzone items; removes past duplicates based on `exclude.sha256`. | Instantly after dumping new files from phones, SD cards, or external backups. | `python3 scripts/register_and_exclude.py`
`start_curation.py` | Initializes the baseline hash snapshot for a new review session. | Right after you manually copy a fresh batch of raw files from Dropzone into Workspace. | `python3 scripts/start_curation.py /path/to/Workspace/Folder`
`append_to_curation.py` | Dynamically hashes late file arrivals and adds them to an active session manifest. | Mid-session, only if you dragged extra files into an explicitly created appended folder. | `python3 scripts/append_to_curation.py /path/to/Workspace/Folder/appended`
`finalize_curation.py` | Cross-references manifests, clears Dropzone entries, builds history capsule, logs keepers. | Once your manual categorization, modifications, and deletions in Workspace are completely done. | *Dry-Run Preview:*<br>`python3 scripts/finalize_curation.py /path/to/Workspace/Folder`<br>*Commit Changes*:<br>`python3 scripts/finalize_curation.py /path/to/Workspace/Folder --commit`


## 🧪 Running Automated Unit Tests

Validate your pipeline modifications inside an isolated temporary sandbox execution environment before committing changes to GitHub:

```{bash}
python3 -m unittest discover -v
```

## ⚠️ Critical Notes & Warnings

* **Privacy Guardrail:** Never commit your active `config.json` file or any file ending in `.sha256` to GitHub. The root `.gitignore` is explicitly structured to block them from going public.

* **Modification Constraint:** Do not alter, edit, or rename files inside the `Dropzone`. The ingestion architecture treats `Dropzone` data as static snapshots. Run all metadata modifications, edits, and consolidations inside the `Workspace` folder.

* **The Invalidation Rule:** Modifying a file inside the `Workspace` changes its hash entirely. If you add extra files mid-session, they must pass through `append_to_curation.py` before you edit them, or the engine will fail to clean the raw duplicates from the `Dropzone`.

* **Resetting registries:** If a file becomes corrupted or misaligned inside your intake path, delete that folder's local `.registered.sha256` track file. The next run will safely rebuild it.
