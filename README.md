# myDigitalLife

myDigitalLife is a small, hash-based pipeline for safely curating family file backups (photos, videos, documents or anything else). It's designed to be simple enough for several non-technical family members to follow the same workflow.

## 📁 Repository & System Structure

### Git Repository Layout

```{text}
myDigitalLife/
  ├── .gitignore                    # Excludes config.json and *.sha256 tracking files
  ├── LICENSE
  ├── README.md
  ├── config.json.template          # Template for your local settings (folder paths, your name)
  ├── config.json                   # Your local private settings (git-ignored)
  ├── scripts/
  │     ├── common.py               # Shared helpers, file name constants, run lock and run log
  │     ├── register_and_exclude.py
  │     ├── preview_pending_removal.py
  │     └── finalize_curation.py
  └── tests/
        ├── __init__.py
        ├── test_register_and_exclude.py
        ├── test_preview_pending_removal.py
        ├── test_finalize_curation.py
        ├── test_lock.py
        └── test_workflow.py        # whole workflow, crash/re-run, logs, config checks
```

### Connected Network Storage Layout

The scripts and this README refer to the folders by their role and by the key in `config.json` (`upload_path`, `excluded_path`, `state_path`, `log_path`). Which names the folders really have is up to you; the names below are only examples.

```{text}
/QNAP_Family_Vault/                     # example names
  ├── Upload/      # the upload folder (upload_path): raw backup intake, never edited by hand.
  │                # Contains only uploaded content.
  ├── State/       # the state folder (state_path): script-owned, do not edit:
  │                #   registered.sha256  - every file seen in the upload folder
  │                #   exclude.sha256     - every file already curated
  │                #   .pipeline.lock     - present only during a run
  ├── Logs/        # the log folder (log_path): one log file per script run, shared by everyone
  │                #   (see "Run logs" below)
  └── Excluded/    # the excluded folder (excluded_path): archive; never read back.
        ├── registration_YYYYMMDD_hhmmss/  # already-curated files caught at registration
        └── curation_YYYYMMDD_hhmmss/     # upload files archived at end of curation session
```

The workspace (where you curate) isn't set in `config.json`. It's session-scoped and can live anywhere: you pass the session folder to the scripts. See below.

### Expected state of the upload folder

- Every new backup goes into its own `<source>/<date>` folder, for example `<upload folder>/Phone1/2026-09-20/`.
- Before `finalize_curation.py` runs, every file in the upload folder must be listed in `registered.sha256`, which means `register_and_exclude.py` has been run after the last dump. Otherwise `finalize_curation.py` aborts and names the `<source>/<date>` folders that still need registering.

## 🔄 Core Pipeline Workflow

```{text}
Step 1: [Upload intake] ────> register_and_exclude.py ──> known curated files moved to
                                     │                     <excluded folder>/registration_.../
                                     ▼ (new files logged in registered.sha256)
Step 2: [Manual Copy] ─────────> copy the batch you want to curate into
                                  <session folder>/Original/  (any internal structure)
                                     │
Step 3: [Manual Copy] ─────────> copy Original/ → <session folder>/Sorted/
                                     │
Step 4: [Curate]  ─────────────> reorganize/rename/delete freely inside Sorted/
                                  (see the rule below about deleting from Original/ too)
                                     │
Step 5: [Preview - optional] ──> preview_pending_removal.py <session folder>
                                  fills ToBeDeleted/ with anything in Original/
                                  that didn't make it into Sorted/, for one last look
                                     │
Step 6: [Dry run] ──────────────> finalize_curation.py <session folder> --dry-run
                                  checks everything and shows what would happen
                                     │
Step 7: [Copy to library] ─────> copy the folders inside Sorted/ into the shared
                                  home folder and check the copy (see below)
                                     │
Step 8: [Finalize] ─────────────> finalize_curation.py <session folder> --commit
                                  matched upload files archived to
                                  <excluded folder>/curation_.../, exclude.sha256 updated
```

## 💻 Script Execution & Commands

All scripts must be executed from the **root directory** of your repository.

The scripts need Python 3 and run on macOS or Linux only. Windows users can take part by copying files by hand (into the upload folder, `Original/`, `Sorted/` and the home folder), but the commands below must be run on a Mac or Linux computer.

Script | Purpose | When to Run | Command
-------| ------- | ----------- | -------
`register_and_exclude.py` | Registers fresh files in the upload folder; auto-excludes anything already fully processed (per `exclude.sha256`). | Right after dumping new files from phones, SD cards, or external backups. | `python3 scripts/register_and_exclude.py`
`preview_pending_removal.py` | Recomputes, from scratch, which files in `Original/` never made it into `Sorted/`, and copies them into `ToBeDeleted/` for review. Never touches `Original/`, `Sorted/` or the upload folder, so it is safe to run as many times as you like. `ToBeDeleted/` is owned by the script and wiped and regenerated on every run, so never keep your own files in it. It also reports whether all files in the upload folder are registered, because `finalize_curation.py` stops otherwise. | Any time during curation, whenever you want a last look before finalizing. | `python3 scripts/preview_pending_removal.py /path/to/session_folder`
`finalize_curation.py` | Aborts if the upload folder holds files not yet registered (run `register_and_exclude.py` first). Hashes `Original/` and `Sorted/` fresh, cross-references the registry, archives the matched files from the upload folder, and updates the shared exclusion ledger. | Once your curation of a session is completely done. | *Dry-Run Preview (changes nothing):*<br>`python3 scripts/finalize_curation.py /path/to/session_folder --dry-run`<br>*Commit Changes:*<br>`python3 scripts/finalize_curation.py /path/to/session_folder --commit`

`finalize_curation.py` always needs one of `--dry-run` or `--commit`. Without either it changes nothing and prints both options, so a preview can never be mistaken for a finished run. Run `--dry-run` first, check the list, then run `--commit`.

There is deliberately no script to create the `Original`/`Sorted` folder pair - `mkdir -p /path/to/session_folder/{Original,Sorted}` (or the Finder equivalent) is simple enough to do by hand, since nothing needs to be initialized.

## 🧭 The Original/Sorted Convention

In your workspace (any folder you like, for example `Workspace/`), create one folder per curation session, containing exactly two subfolders.

Name the session folder `<YourName>_<YYYY-MM-DD>`, for example `Gosia_2026-09-25`: the person doing the curation and the date the session started. The scripts don't depend on the name, it only helps family members see whose session a folder is.

The two subfolders are:

- **`Original/`** - an untouched copy of whatever you pulled from the upload folder for this session. Any internal structure is fine; hashing doesn't care about folder layout.
  You can add more files to `Original/` at any time during the session, also remotely through Dropbox. A file you add later and want to keep must also be copied into `Sorted/`; otherwise it counts as dropped (it then shows up in `ToBeDeleted/` and in the "only in `Original/`" count).
- **`Sorted/`** - your actual working copy. Reorganize, rename, move into categories, delete - whatever you want, as much as you want, as many times as you want.

`finalize_curation.py` treats a file as "handled" if its hash shows up **anywhere in `Original/` OR `Sorted/`** - not just in `Sorted/`. This is deliberate: it's what lets you freely delete things from `Sorted/` mid-session (because you decided you don't want that file in your final layout) while the corresponding file in the upload folder still gets safely archived, since you did review it.

**The one rule to remember:** if you remove a file from `Sorted/` because you've changed your mind and do **not** want its original in the upload folder archived at all (i.e. you don't want it treated as reviewed), you must also delete it from `Original/`. Otherwise its mere presence in `Original/` is enough to mark it "handled".

**What gets recorded in `exclude.sha256`:** the content of everything you curated, so that the same content is recognized and moved to the excluded folder if it is ever uploaded again. That is (1) every file in the upload folder that matches something in `Original/` or `Sorted/`, (2) every file in `Original/` that the upload folder doesn't know, and (3) **every file in `Sorted/`**, also edited versions and files that never came through the upload folder. Point 3 matters because an edited file (rotated, cropped, re-saved) has new content: without its own entry, the same edited file uploaded later would be offered for curation again.

**Never edit files inside `Original/`** (no rotating, re-saving or renaming in an editor): a changed file no longer matches its original in the upload folder, so that original would stay behind there. Do your edits on the copy in `Sorted/`. The summary at the end of `finalize_curation.py` (also in `--dry-run`) shows how many files are in `Original/`, in `Sorted/`, in both `Original/` and `Sorted/`, only in `Original/` and only in `Sorted/`, so you can check that the numbers match what you did.

**Duplicate filing is not supported.** If the exact same file content ends up at two different paths inside `Sorted/` (e.g. filed under both "Family" and "Beach"), `finalize_curation.py` will print both paths and abort before touching anything. Resolve it by keeping only one copy and re-run.

## 📦 Copying the curated folders to the shared home folder

Do this after `finalize_curation.py --dry-run` looks right and **before** `--commit`. That way, whatever is recorded as done is already saved in the home folder. The scripts don't copy anything for you.

Copy the folders that are inside `Sorted/` (for example `Holiday/`), not the `Sorted` folder itself, so they end up directly in the home folder. The files you copy should not already exist there. Never overwrite anything.

**By hand (Windows, or if you prefer not to use the terminal):** open `Sorted/`, select everything inside it and drag it into the home folder. If you're asked what to do about files that already exist, choose to **skip** them or **cancel**, never "replace". Then spot-check that a few folders and files arrived.

**With rsync (macOS and Linux):**

```{bash}
# 1. Preview what would be copied (changes nothing)
rsync -avn --ignore-existing "/path/to/session_folder/Sorted/" "/path/to/home_folder/"

# 2. Copy, never overwriting anything that already exists
rsync -av --ignore-existing "/path/to/session_folder/Sorted/" "/path/to/home_folder/"

# 3. Verify by content: apart from rsync's summary lines, this must list no file names
rsync -avnc "/path/to/session_folder/Sorted/" "/path/to/home_folder/"
```

The slash after `Sorted/` matters: it copies the contents of `Sorted/` (your folders), while `Sorted` without a slash would create an extra `Sorted` folder inside the home folder. A folder that already exists in the home folder is merged into, not replaced. If step 3 lists a file, it was not copied, or a different file with the same name was already there; fix that before running `finalize_curation.py --commit`.

## ☁️ Syncing with Dropbox

This is for a setup where the scripts run on a Mac or Linux computer with the QNAP mounted, while devices upload to Dropbox and people curate away from home. The sync itself is done on the QNAP (for example with Hybrid Backup Sync, HBS 3), so the scripts and the sync tool work on the same files. Menu names differ between QTS versions, so set it up first with a throwaway session and batch, not with real data.

| Folder | Sync direction | Why |
|---|---|---|
| upload folder | two-way | devices upload into it, and files moved out by the scripts disappear from Dropbox too (a one-way copy would bring them back on every cycle) |
| workspace | two-way | curation away from home |
| Home folder (curated library) | one-way, QNAP to Dropbox | Dropbox is only the second copy; changes made in Dropbox must not alter the QNAP. If the job can keep files that were deleted on the QNAP, switch that on |
| state folder | one-way, QNAP to Dropbox | gives `registered.sha256` and `exclude.sha256` a versioned backup that nobody on the Dropbox side can change or delete |
| log folder | one-way, QNAP to Dropbox | read the logs from anywhere |
| excluded folder | not synced | archive, written by the scripts only |

**Rules for the sync jobs**
- Conflict policy: keep both or rename, never overwrite or "newest wins".
- Use the shortest sync interval the job allows. Two-way sync is not instant.
- Keep `Original/` in the workspace sync. People add files to `Original/` during curation, also from Dropbox when the QNAP can't be reached, so it must sync like `Sorted/`. The price is Dropbox space: every batch takes about three times its size (the files in the upload folder, `Original/` and `Sorted/`). Deleting the session folder after `--commit` frees it again.
- Nothing in the state folder may ever be edited or deleted by hand, on any computer.

**Rules for everyone using the scripts**
- Run the scripts on the QNAP path (the mounted share), never on a Dropbox copy of a folder.
- Run `register_and_exclude.py` only when the upload folder's sync has finished (the Dropbox app says "up to date" and the HBS job is idle). A file that is hashed while it is still arriving gets a wrong hash in the registry, and its original in the upload folder is then never archived.
- Before `finalize_curation.py`, wait until the workspace sync has finished. If it finds "conflicted copy" files it stops (see below).
- Uploads can arrive at any time. If `finalize_curation.py` stops because the upload folder holds unregistered files, run `register_and_exclude.py` once the sync is idle, then run it again.
- Camera upload apps put files in one flat folder, not in `<source>/<date>` folders. The scripts still work; only the grouped messages and the empty-folder cleanup assume `<source>/<date>`.
- After `--commit` and copying to the home folder, delete the session folder in the workspace. The deletion syncs and frees the Dropbox space.

### What is a "conflicted copy"?

If the same file is changed in two places before the sync has caught up (you rename or edit a photo in `Sorted/` on your laptop while the QNAP, or another person, changes the same file), Dropbox cannot tell which version is right. It keeps both and renames one of them, for example `photo (Anna's conflicted copy 2026-11-13).jpg`. Dropbox's other variant is `photo (Case Conflict 1).jpg`, and folders can get such names too. A sync job set to "keep both" does the same. The names are a sign that two versions of one file exist and nobody has chosen yet.

This matters because finalizing would put both versions into the home folder, or stop with a confusing duplicate message. So `finalize_curation.py` (also with `--dry-run`) checks `Original/` and `Sorted/` first. If a file or folder name contains "conflicted copy" or "case conflict" (upper or lower case), it stops, changes nothing, and lists the files.

What to do for each listed file:
1. Open both versions and decide which one is right.
2. Delete the other one.
3. If you keep the one with the conflict name, rename it so that the words "conflicted copy" are gone.
4. Run `finalize_curation.py` again.

A file that really has those words in its name for another reason must be renamed too, otherwise the check keeps stopping.

Dropbox is a sync service, not a full backup: it keeps deleted files and old versions only for a limited time. Keep that in mind when you rely on it as the second copy.

## 🧪 Running Automated Unit Tests

Validate your pipeline modifications inside an isolated temporary sandbox before committing changes to GitHub:

```{bash}
python3 -m unittest discover -v
```

## ⚠️ Critical Notes & Warnings

* **Privacy Guardrail:** Never commit your active `config.json` or any file ending in `.sha256` to GitHub. The root `.gitignore` blocks them from ever going public - this matters because this repository is public.

* **Modification Constraint:** Do not alter, edit, or rename anything inside the upload folder by hand. It's treated as an immutable, append-only snapshot; all sorting and deleting happens inside the session folder's `Sorted/`.

* **The upload folder keeps every incoming copy:** if the same file arrives more than once (another phone, another card, another day), every copy is registered and kept until it has been curated. Only content that was already curated in a past session is moved to the excluded folder on intake. When a session is finalized, every copy of a handled file in the upload folder is archived together.

* **Set your name once:** copy `config.json.template` to `config.json` and replace `"user_name": "CHANGE_ME"` with your own name (for example `"Gosia"`) and set `"log_path"` (the shared folder for logs) and `"state_path"` (the folder for the registry, the ledger and the run lock; it must not be inside the upload folder). `register_and_exclude.py` and `finalize_curation.py` refuse to run until you do, because they record who registered and who finalized every file.

* **Run logs:** every run of `register_and_exclude.py`, `preview_pending_removal.py` and `finalize_curation.py` (dry runs too) writes a log file to the shared `log_path` folder from `config.json`, named like `20261113_134237_finalize_curation_Gosia.log`. It contains everything that was printed in the terminal, a header (who, which computer, which arguments) and how the run ended, including the full error if it crashed. Look there when something unexpected happened, also on someone else's run. The scripts refuse to run if the log folder cannot be written, and logs are never deleted automatically. `log_path` must not be inside the upload folder. Logs contain file names, so never commit them.

* **One upload folder, one config:** `register_and_exclude.py` always operates on `config.json`'s `upload_path` - there's no way to point it at a different folder for a given run. This is intentional: with only one upload folder, a session can never end up ambiguous about which upload folder it came from.

* **Folder names live in `config.json` only:** the scripts never depend on what the folders are called. A `config.json` from an older version that still has the key `dropzone_path` makes the scripts stop and ask you to rename it to `upload_path`.

* **Shared file names:** both scripts take the names `registered.sha256` and `exclude.sha256` from `scripts/common.py`.

* **Every script is safe to run again** after a crash, a closed laptop or a lost network connection. `register_and_exclude.py` and `finalize_curation.py` write their lists in a way that can't leave them half-written, and `finalize_curation.py` picks up where it stopped. Files already moved to the excluded folder stay there (one cut off mid-copy may be left incomplete there; the original is still in the upload folder and is moved again on the re-run).

* **The scripts stop instead of guessing.** `finalize_curation.py` refuses to run, and changes nothing, if a file in `Original/` or `Sorted/` can't be read, if the upload folder contains unregistered files, if `Original/` or `Sorted/` contain Dropbox "conflicted copy" files, or if the same content is in `Sorted/` twice. Both scripts refuse folder setups where the excluded folder or a session folder lies inside the upload folder.

* **Empty folders are cleaned up:** when `register_and_exclude.py` or `finalize_curation.py` moves the last file out of a `<source>/<date>` folder, that folder is removed (hidden Finder/Windows files in it don't count). Only folders the run itself emptied are touched, and the `<source>` folder (for example `Phone1/`) always stays. The dry run lists the folders it would remove, and the log lists the ones removed.

* **Files that are skipped:** macOS and Windows metadata (`._*`, `.DS_Store`, `Thumbs.db`, `desktop.ini`). Files whose names contain a tab or line break are not registered; the summary lists them so you can rename them.

* **One run at a time:** while `register_and_exclude.py` or `finalize_curation.py` runs, it holds a lock (a `.pipeline.lock` folder in the state folder), so a second run, even from another computer, stops and tells you who is running what. The lock is removed automatically when the run ends, fails or is interrupted. If a computer crashes or loses power mid-run, a leftover lock from that same computer is removed on the next run. A leftover lock from another computer is not removed automatically: the message names the owner, and if you are sure nobody is running the scripts, delete the `.pipeline.lock` folder it points to.

* **`registered.sha256` and `exclude.sha256` live in the state folder:** older versions kept them inside the upload folder. If a script finds them there it stops and tells you to move them to the state folder by hand.

* **Resetting the registry:** If `registered.sha256` in the state folder ever becomes corrupted or misaligned, delete it. The next `register_and_exclude.py` run will safely rebuild it from whatever is actually in the upload folder (already-excluded content will just be skipped again via `exclude.sha256`).
