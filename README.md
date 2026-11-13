# myDigitalLife

myDigitalLife is a small, hash-based pipeline for safely curating family file backups (photos, videos, documents or anything else) across a Dropzone intake folder, a Workspace curation area, and an archive, on shared network storage. It's designed to be simple enough for several non-technical family members to follow the same workflow.

## 📁 Repository & System Structure

### Git Repository Layout

```{text}
myDigitalLife/
  ├── .gitignore                    # Excludes config.json and *.sha256 tracking files
  ├── config.json.template          # Template profile for required storage keys
  ├── config.json                   # Local private path mapping (git-ignored)
  ├── scripts/
  │     ├── common.py               # Shared hashing/config helpers and file name constants
  │     ├── register_and_exclude.py
  │     ├── preview_pending_removal.py
  │     └── finalize_curation.py
  └── tests/
        ├── __init__.py
        ├── test_register_and_exclude.py
        ├── test_preview_pending_removal.py
        └── test_finalize_curation.py
```

### Connected Network Storage Layout

```{text}
/QNAP_Family_Vault/
  ├── Dropzone/    # Intake for raw backups. Treated as immutable - never edited by hand.
  │                #   registered.sha256  - every file already seen here, with hash, path and registration time
  │                #   exclude.sha256     - hashes already fully processed in a past session
  └── Excluded/    # Archive. Nothing here is ever read back automatically.
        ├── registration_YYYYMMDD_hhmmss/  # duplicates caught on intake, one folder per run
        └── curation_YYYYMMDD_hhmmss/     # originals archived once a curation session is done
```

### Expected state of Dropzone

Every new backup goes into its own `<source>/<date>` folder, for example `Dropzone/Phone1/2026-09-20/`. The scripts don't enforce this, but `finalize_curation.py` relies on it to report unregistered files by folder.

Before `finalize_curation.py` runs, every file in Dropzone must be listed in `registered.sha256`, which means `register_and_exclude.py` has been run after the last dump. Otherwise `finalize_curation.py` aborts and names the `<source>/<date>` folders that still need registering.

`Workspace/` (where you do the actual sorting) isn't part of the storage layout above because it's entirely session-scoped and lives wherever you like - see below.

## 🔄 Core Pipeline Workflow

```{text}
Step 1: [Dropzone Intake] ──> register_and_exclude.py ──> known duplicates moved to
                                     │                     Excluded/registration_.../
                                     ▼ (new files logged in registered.sha256)
Step 2: [Manual Copy] ─────────> copy the batch you want to curate into
                                  Workspace/Name_Date/Original/  (any internal structure)
                                     │
Step 3: [Manual Copy] ─────────> copy Original/ → Workspace/Name_Date/Sorted/
                                     │
Step 4: [Curate]  ─────────────> reorganize/rename/delete freely inside Sorted/
                                  (see the rule below about deleting from Original/ too)
                                     │
Step 5: [Preview - optional] ──> preview_pending_removal.py Name_Date
                                  fills ToBeDeleted/ with anything in Original/
                                  that didn't make it into Sorted/, for one last look
                                     │
Step 6: [Finalize] ─────────────> finalize_curation.py Name_Date --dry-run | --commit
                                  matched Dropzone originals archived to
                                  Excluded/curation_.../, exclude.sha256 updated
```

## 💻 Script Execution & Commands

All scripts must be executed from the **root directory** of your repository.

Script | Purpose | When to Run | Command
-------| ------- | ----------- | -------
`register_and_exclude.py` | Registers fresh Dropzone items; auto-excludes anything already fully processed (per `exclude.sha256`). | Right after dumping new files from phones, SD cards, or external backups. | `python3 scripts/register_and_exclude.py`
`preview_pending_removal.py` | Recomputes, from scratch, which files in `Original/` never made it into `Sorted/`, and copies them into `ToBeDeleted/` for review. Never touches `Original/`, `Sorted/` or Dropzone, so it is safe to run as many times as you like. `ToBeDeleted/` is owned by the script and wiped and regenerated on every run, so never keep your own files in it. | Any time during curation, whenever you want a last look before finalizing. | `python3 scripts/preview_pending_removal.py /path/to/Workspace/Name_Date`
`finalize_curation.py` | Aborts if Dropzone holds files not yet registered (run `register_and_exclude.py` first). Hashes `Original/` and `Sorted/` fresh, cross-references the Dropzone registry, archives matched Dropzone originals, and updates the shared exclusion ledger. | Once your curation of a `Name_Date` session is completely done. | *Dry-Run Preview (changes nothing):*<br>`python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date --dry-run`<br>*Commit Changes:*<br>`python3 scripts/finalize_curation.py /path/to/Workspace/Name_Date --commit`

`finalize_curation.py` always needs one of `--dry-run` or `--commit`. Without either it changes nothing and prints both options, so a preview can never be mistaken for a finished run. Run `--dry-run` first, check the list, then run `--commit`.

There is deliberately no script to create the `Original`/`Sorted` folder pair - `mkdir -p Workspace/Name_Date/{Original,Sorted}` (or the Finder equivalent) is simple enough to do by hand, since nothing needs to be initialized.

## 🧭 The Original/Sorted Convention

Inside `Workspace/`, create one folder per curation session, containing exactly two subfolders.

Name the session folder `<YourName>_<YYYY-MM-DD>`, for example `Gosia_2026-09-25`: the person doing the curation and the date the session started. The scripts don't depend on the name, it only helps family members see whose session a folder is.

The two subfolders are:

- **`Original/`** - an untouched copy of whatever you pulled from Dropzone for this session. Any internal structure is fine; hashing doesn't care about folder layout.
- **`Sorted/`** - your actual working copy. Reorganize, rename, move into categories, delete - whatever you want, as much as you want, as many times as you want.

`finalize_curation.py` treats a file as "handled" if its hash shows up **anywhere in `Original/` OR `Sorted/`** - not just in `Sorted/`. This is deliberate: it's what lets you freely delete things from `Sorted/` mid-session (because you decided you don't want that file in your final layout) while the corresponding Dropzone original still gets safely archived, since you did review it.

**The one rule to remember:** if you remove a file from `Sorted/` because you've changed your mind and do **not** want its Dropzone original archived at all (i.e. you don't want it treated as reviewed), you must also delete it from `Original/`. Otherwise its mere presence in `Original/` is enough to mark it "handled".

**Duplicate filing is not supported.** If the exact same file content ends up at two different paths inside `Sorted/` (e.g. filed under both "Family" and "Beach"), `finalize_curation.py` will print both paths and abort before touching anything. Resolve it by keeping only one copy and re-run.

## 🧪 Running Automated Unit Tests

Validate your pipeline modifications inside an isolated temporary sandbox before committing changes to GitHub:

```{bash}
python3 -m unittest discover -v
```

## ⚠️ Critical Notes & Warnings

* **Privacy Guardrail:** Never commit your active `config.json` or any file ending in `.sha256` to GitHub. The root `.gitignore` blocks them from ever going public - this matters because this repository is public.

* **Modification Constraint:** Do not alter, edit, or rename anything inside `Dropzone/` by hand. It's treated as an immutable, append-only snapshot; all sorting and deleting happens inside `Workspace/Name_Date/Sorted/`.

* **Dropzone keeps every incoming copy:** if the same file arrives more than once (another phone, another card, another day), every copy is registered and kept until it has been curated. Only content that was already curated in a past session is moved to `Excluded/` on intake. When a session is finalized, every Dropzone copy of a handled file is archived together.

* **One Dropzone, one config:** `register_and_exclude.py` always operates on `config.json`'s `dropzone_path` - there's no way to point it at a different folder for a given run. This is intentional: with only one Dropzone, a `Workspace` session can never end up ambiguous about which Dropzone it came from.

* **Shared file names:** both scripts take the names `registered.sha256` and `exclude.sha256` from `scripts/common.py`.

* **Every script is safe to run again** after a crash, a closed laptop or a lost network connection. `register_and_exclude.py` and `finalize_curation.py` write their lists in a way that can't leave them half-written, and `finalize_curation.py` picks up where it stopped. Files already moved to `Excluded/` stay there (one cut off mid-copy may be left incomplete there; the original is still in Dropzone and is moved again on the re-run).

* **The scripts stop instead of guessing.** `finalize_curation.py` refuses to run, and changes nothing, if a file in `Original/` or `Sorted/` can't be read, if Dropzone contains unregistered files, or if the same content is in `Sorted/` twice. Both scripts refuse folder setups where `Excluded/` or a session folder lies inside Dropzone.

* **Files that are skipped:** macOS and Windows metadata (`._*`, `.DS_Store`, `Thumbs.db`, `desktop.ini`). Files whose names contain a tab or line break are not registered; the summary lists them so you can rename them.

* **One person at a time:** run `register_and_exclude.py` and `finalize_curation.py` only when nobody else is running either of them on the same Dropzone.

* **Resetting the registry:** If `registered.sha256` ever becomes corrupted or misaligned, delete it. The next `register_and_exclude.py` run will safely rebuild it from whatever is actually in Dropzone (already-excluded content will just be skipped again via `exclude.sha256`).
