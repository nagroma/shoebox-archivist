# Shoebox Archivist - notes for developers and AI assistants

Family photo library manager: local face recognition, fuzzy (EDTF) dates, photo backs.
Must run on Windows and macOS. Plan: see docs/PLAN.md.

## Commands
- `uv sync` - install deps (onnxruntime-gpu on Win/Linux, onnxruntime on macOS)
- `uv run pytest` - tests
- `uv run pm --help` - prototype CLI (ingest, review, label, reject, ignore, date, evaluate, status, strip, baseline)
- `uv run pm ingest <folder> --rescan` - re-detect faces in every photo, keeping existing faces/names (`--rescan-empty`: only photos with none; `--fast`: fast mode for this run)
- `cd frontend && npm install && npm run build` then `uv run pm serve` - web UI at http://127.0.0.1:8765
- UI dev with hot reload: `uv run pm serve --no-browser` + `cd frontend && npm run dev` (http://localhost:5173, proxies /api)
- Backend: `backend/api.py` (FastAPI) and `backend/actions.py` (state changes shared with the CLI)
- Libraries: `uv run pm serve`, then choose a photo folder in the web UI (reads the keywords already in it, proposes facets, creates the library, starts the import). The app's data lives in `<photo folder>/.shoebox/` (`backend/library.py`); Settings-like management is at `/library` (facets, Keywords.txt export, reset). `pm serve` reopens the last library; `pm --library <folder> <cmd>` targets one from the CLI.
- A library's data folder moves with its photo folder: renaming or moving the folder is fine (the stored root is corrected when the database opens). `~/.shoebox-archivist/state.json` only remembers the last folder; if it is stale, pick the folder again in the UI.
- `PM_DATA=<dir>` - older setup: keeps the DB, face thumbnails and report.html in `<dir>` instead of `.shoebox` (default `./data` when no library was chosen in the UI)
- GPU on Windows: CUDA 13 + cuDNN 9 come from `nvidia-*` pip wheels (`uv sync`); needs an NVIDIA driver supporting CUDA 13. No system CUDA install.
- `PM_PROVIDER=cpu` - force CPU inference
- User settings: `backend/config.py` (`config.load(conn)`), stored as JSON in `settings.config`, shown at `/settings`, API `GET/PUT /api/settings`. A function argument or CLI flag of `None` means "use the setting".

## Rules
- `docs/DECISIONS.md` holds the foundations and guardrails (with the reason for each). If a request would break one, stop and ask. When a choice is made because the alternative caused or would cause a problem, add it there with the why.
- Metadata lives in each photo's XMP (keywords in `lr:hierarchicalSubject`); read and write it with pyexiv2 (`backend/xmp.py`). Keyword conventions: docs/KEYWORD_RULES.md.
- Bridge and Lightroom are used in parallel with this app (the collection owner manages their photos in Bridge); compatibility with both is a core requirement. Whatever the app writes must read cleanly in Bridge and Lightroom, and edits made there are picked up on the next import.
- Existing keywords are never lost or silently duplicated. Every hierarchical or flat keyword in a file is kept with its exact path (`Ashdown|JuliaAshdown` stays `Ashdown|JuliaAshdown`, even though Bridge's `[Ashdown]` bracket suggests it shouldn't appear in files). The app does not invent a second keyword (`People|JuliaAshdown`) for something that already exists under another group; changing keyword paths is an explicit remap (file-wide, with provenance), never a side effect. New groups found in photos added later are surfaced for the user to add as a facet or map, not ignored.
- The owner's current keyword design (see docs/KEYWORD_STRATEGY.md §1) differs from the app's default: `Ashdown|X`, `Marlowe|X`, `AshdownMarlowe|X` are people grouped by family, and `People` holds only people outside those three families. The default (`People` = everyone, `Family|<Name>` = family) is a proposal he has not accepted; the app must work with his structure unchanged (several `person` facets) and offer the migration (`pm regroup`) as an option, never assume it.
- `Keywords.txt` and the legacy `PM_DATA`/`./data` library are from earlier iterations: do not build on them.
- Bridge/Lightroom keywords are the mechanism: no app-specific keyword format. Each library has its own facets (top-level groups, each with a kind) in its DB; the app mirrors the file keywords and can export a `Keywords.txt` for Bridge/Lightroom (it never reads one). Keyword `category` is the full parent path (`Places|USA`), `name` the leaf.
- Nothing in code or tests may assume one family's names. Collection-specific structure belongs in a library's facets/vocabulary (docs/KEYWORD_STRATEGY.md is one collection's proposal, kept as an example).
- The app may modify original photos, but only with provenance:
  - Every app-added keyword goes in `sa:AddedKeywords`.
  - Edited fields keep their prior value in `sa:Original*`.
  - `pm strip` undoes app edits; `pm baseline save/restore` snapshots the library for dev testing.
- Never touch a Lightroom catalog.
- Store paths relative to the library root with `/` separators.
- Face naming is suggest-then-confirm. A photo with exactly one person keyword and one detected face is *suggested* from the keyword (`label_source='keyword'`) for bulk confirmation; the `keyword_autoconfirm` setting (default off) confirms it without review. Changes to existing keywords (`backend/regroup.py`, `pm regroup`) are previewed and need explicit confirmation.
- Name changes: the keyword in the files stays under the person's primary (birth) name. Other names live in `person_names` (kind, `from_year`); photos dated from that year show the alias (`person_name` in `api.FACE_SQL`), and typing an alias resolves to the same person. Edit at `/people/<id>` ("Other names"), API `PUT /api/people/{id}/aliases`.
- Family: only `relations` rows are stored (parent_of, partner) - siblings, grandparents, cousins and labels are derived from them by `backend/family.py`, measured from the library's curator. Labels are gender-neutral (no gender is recorded).
- Family tree view: `GET /api/family/{id}?generations=N` (nodes with generation + links, from `family.circle`), drawn by `frontend/src/pages/Tree.tsx`; the photos list takes `family_id` + `generations`.
- Name shown: `names.pick(main name, name_from_year, aliases, photo year)` - used for face labels, keyword chips, People and tree (year None = the name in use now). The keyword in the files never changes. People notes are app-only (never written to files).
- Branch keywords: `family.branches` (a branch = descendants of someone with no recorded parents, named by their birth surname; a blood relative of the curator also takes a married-in partner's branches, not the other way round) and `actions.sync_branch_keywords` write `Family|<Branch>` to photos with provenance; it only removes ones it created (`branch_keyword_ids` setting) and only if app-written. First run is the button on the Tree page; after that `actions.auto_branches` keeps the photos you name current.
- Dates are EDTF + date_min/date_max; see `backend/dates.py`.
- Faces found only by an extra detection pass get `faces.candidate = 1`. They are kept out of clustering, matching and keyword auto-naming until a person clicks **Face** (`actions.verify_faces`). **Not a face** = status `ignored`.
- `backend/candidates.py` scores pending candidates against earlier decisions, to sort and pre-select them in the UI only. Never auto-hide or auto-verify.
- No real names in the repository, tests, docs or commit messages: use docs/FICTIONAL_NAMES.md. `tests/test_no_real_names.py` checks against gitignored local files (`Keywords.txt`, `.private-names.txt`). Refer to the collection owner as "the owner".
