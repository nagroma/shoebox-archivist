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
- `PM_DATA=<dir>` - where the DB, face thumbnails and report.html go (default `./data`)
- GPU on Windows: CUDA 13 + cuDNN 9 come from `nvidia-*` pip wheels (`uv sync`); needs an NVIDIA driver supporting CUDA 13. No system CUDA install.
- `PM_PROVIDER=cpu` - force CPU inference
- User settings: `backend/config.py` (`config.load(conn)`), stored as JSON in `settings.config`, shown at `/settings`, API `GET/PUT /api/settings`. A function argument or CLI flag of `None` means "use the setting".

## Rules
- Metadata lives in each photo's XMP (keywords in `lr:hierarchicalSubject`); read and write it with pyexiv2 (`backend/xmp.py`). Keyword conventions: docs/KEYWORD_RULES.md.
- The app may modify original photos, but only with provenance:
  - Every app-added keyword goes in `pm:AddedKeywords`.
  - Edited fields keep their prior value in `pm:Original*`.
  - `pm strip` undoes app edits; `pm baseline save/restore` snapshots the library for dev testing.
- Never touch a Lightroom catalog.
- Store paths relative to the library root with `/` separators.
- Face naming is suggest-then-confirm. The only exception: a photo with exactly one person keyword and one detected face is auto-confirmed (`label_source='keyword'`).
- Dates are EDTF + date_min/date_max; see `backend/dates.py`.
- Faces found only by an extra detection pass get `faces.candidate = 1`. They are kept out of clustering, matching and keyword auto-naming until a person clicks **Face** (`actions.verify_faces`). **Not a face** = status `ignored`.
- `backend/candidates.py` scores pending candidates against earlier decisions, to sort and pre-select them in the UI only. Never auto-hide or auto-verify.
