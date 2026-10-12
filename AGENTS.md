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
- Metadata lives in each photo's XMP (keywords in `lr:hierarchicalSubject`); read and write it with pyexiv2 (`backend/xmp.py`). Keyword conventions: docs/KEYWORD_RULES.md.
- Bridge/Lightroom keywords are the mechanism: no app-specific keyword format. Each library has its own facets (top-level groups, each with a kind) in its DB; the app mirrors the file keywords and exports/imports `Keywords.txt`. Keyword `category` is the full parent path (`Places|USA`), `name` the leaf.
- Nothing in code or tests may assume one family's names. Collection-specific structure belongs in a library's facets/vocabulary (docs/KEYWORD_STRATEGY.md is one collection's proposal, kept as an example).
- The app may modify original photos, but only with provenance:
  - Every app-added keyword goes in `pm:AddedKeywords`.
  - Edited fields keep their prior value in `pm:Original*`.
  - `pm strip` undoes app edits; `pm baseline save/restore` snapshots the library for dev testing.
- Never touch a Lightroom catalog.
- Store paths relative to the library root with `/` separators.
- Face naming is suggest-then-confirm. The only exception: a photo with exactly one person keyword and one detected face is auto-confirmed (`label_source='keyword'`).
- Name changes: the keyword in the files stays under the person's primary (birth) name. Other names live in `person_names` (kind, `from_year`); photos dated from that year show the alias (`person_name` in `api.FACE_SQL`), and typing an alias resolves to the same person. Edit at `/people/<id>` ("Other names"), API `PUT /api/people/{id}/aliases`.
- Family: only `relations` rows are stored (parent_of, partner) - siblings, grandparents, cousins and labels are derived from them by `backend/family.py`, measured from the library's curator. Labels are gender-neutral (no gender is recorded).
- Family tree view: `GET /api/family/{id}?generations=N` (nodes with generation + links, from `family.circle`), drawn by `frontend/src/pages/Tree.tsx`; the photos list takes `family_id` + `generations`.
- Name shown: `names.pick(main name, name_from_year, aliases, photo year)` - used for face labels, keyword chips, People and tree (year None = the name in use now). The keyword in the files never changes. People notes are app-only (never written to files).
- Branch keywords: `family.branches` (a branch = descendants of someone with no recorded parents, named by their birth surname; a blood relative of the curator also takes a married-in partner's branches, not the other way round) and `actions.sync_branch_keywords` write `Family|<Branch>` to photos with provenance; it only removes ones it created (`branch_keyword_ids` setting) and only if app-written. First run is the button on the Tree page; after that `actions.auto_branches` keeps the photos you name current.
- Dates are EDTF + date_min/date_max; see `backend/dates.py`.
- Faces found only by an extra detection pass get `faces.candidate = 1`. They are kept out of clustering, matching and keyword auto-naming until a person clicks **Face** (`actions.verify_faces`). **Not a face** = status `ignored`.
- `backend/candidates.py` scores pending candidates against earlier decisions, to sort and pre-select them in the UI only. Never auto-hide or auto-verify.
