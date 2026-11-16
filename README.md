# Shoebox Archivist

A local-first manager for **historic family photo collections**. It does three things:

- **Recognizes faces** with on-device face recognition, learning from people you've already named or keyworded.
- **Handles fuzzy dates** like `c. 1925`, `1920s`, or `1920–1925`, stored as [EDTF](https://www.loc.gov/standards/datetime/).
- **Keeps metadata in the photos**, as Lightroom/Bridge-compatible XMP keywords, captions and dates, so the files stay the source of truth.

> Status: working prototype. Runs on Windows and macOS.

## Features
- **Face recognition** (InsightFace / ArcFace via ONNX Runtime). It uses your NVIDIA GPU on Windows and CoreML/CPU on macOS.
  - Photos already keyworded with people's names seed recognition: the keyword suggests the name, and you confirm.
  - New faces are *suggested*, never silently assigned.
- **Thorough face detection** (default): extra contrast-enhanced, enlarged and rotated passes catch tilted, small and faded faces. Detections that might not be faces go to a *Possible faces* list for a quick yes/no. The list learns from those answers: it sorts and pre-selects likely non-faces, but never hides anything on its own.
- **Keyword-aware matching.** In a photo tagged "Jane Doe, John Doe", the two faces are matched only against those two people.
- **Fuzzy dates** you type naturally ("summer 1948", "c. 1925"). Sorting and filtering use a date range.
- **Multi-photo editing.** Select many photos and set the date, location, caption or keywords at once. Fields that differ show `<...>`.
- **Photo backs.** `_b` / `-back` scans are paired with their fronts, and you can transcribe the handwriting.
- **Safe edits to originals.** Every change the app writes to a file is tracked in its own XMP namespace and can be undone with `pm strip`.
- **Settings page** for detection mode and passes, suggestion threshold, auto-naming from keywords and cluster size. The settings are stored in the library database and shared with the CLI.

## Requirements
| | Windows 10/11 | macOS |
|---|---|---|
| OS | 64-bit | **macOS 15 (Sequoia) or later** (needed by the `pyexiv2` wheels) |
| Python | 3.12 (installed by `uv`) | 3.12 (installed by `uv`) |
| Package manager | [uv](https://docs.astral.sh/uv/) | [uv](https://docs.astral.sh/uv/) |
| Node.js | 20+ (for the web UI build) | 20+ |
| GPU (optional) | NVIDIA with a driver that supports CUDA 13. The CUDA/cuDNN runtime comes from pip wheels, so there's no separate CUDA install. | Apple Silicon uses CoreML automatically |

Without a GPU everything still works. Face detection takes roughly 1 second per photo per pass on a CPU, and thorough mode runs about 8 passes. Switch to *Fast* in Settings if that's too slow.

## Setup

### 1. Install the tools
**Windows (PowerShell):**
```powershell
winget install --id=astral-sh.uv -e
winget install OpenJS.NodeJS.LTS
```
**macOS:**
```bash
brew install uv node
```

### 2. Get the code and dependencies
```bash
git clone https://github.com/nagroma/shoebox-archivist.git
cd shoebox-archivist
uv sync                                  # creates .venv, installs Python + all deps
cd frontend && npm install && npm run build && cd ..
```
The first face scan downloads the InsightFace `buffalo_l` model (~300 MB) to `~/.insightface/`.

### 3. Add photos and run
```bash
uv run pm ingest path/to/photos          # register photos, read metadata, find faces
uv run pm serve                          # opens http://127.0.0.1:8765
```
The folder you ingest first becomes the **library root**. All paths are stored relative to it, so the library can move between machines.

You can also add photos from the UI with **Add photos**: drag and drop, or scan the library folder.

## Development
```bash
uv run pytest                            # tests
uv run pm --help                         # CLI: ingest, review, label, date, status, strip, baseline…
uv run pm ingest <folder> --rescan       # re-check scanned photos with the current detection settings
uv run pm serve --no-browser             # API on :8765 …
cd frontend && npm run dev               # … UI with hot reload on http://localhost:5173 (proxies /api)
```

| Env var | Meaning |
|---|---|
| `PM_DATA=<dir>` | Where the database, face thumbnails and caches live (default `./data`) |
| `PM_PROVIDER=cpu` | Force CPU inference |

User settings (Settings page) live in the DB `settings` table, under the key `config`; see `backend/config.py`. CLI flags such as `--fast`, `--threshold` and `--min-size` override them for one run.

### Resetting to a known state
The app writes keywords, captions, dates and locations into the original files, so there are two ways to undo its changes:
```bash
uv run pm baseline save                  # snapshot the library files (dev/testing)
uv run pm baseline restore               # put files back + wipe the DB, then re-ingest
uv run pm strip                          # remove only what the app wrote (keeps everyone else's edits)
```

### Project layout
```
backend/     Python: FastAPI app (api.py), CLI (cli.py), ingest, faces, match, cluster,
             candidates (possible-face scoring), config (settings), xmp, keywords, dates
frontend/    React + TypeScript + Vite web UI
tests/       pytest
docs/        PLAN.md, KEYWORD_RULES.md, USER_GUIDE.md
```
- Read **[AGENTS.md](AGENTS.md)** before contributing; it holds the project rules.
- Keyword conventions are in **[docs/KEYWORD_RULES.md](docs/KEYWORD_RULES.md)**.
- End-user help is in **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

### Troubleshooting
- **"Failed to load cublasLt64_13.dll" / provider is CPU on Windows.** Update the NVIDIA driver to one that supports CUDA 13, then run `uv sync` again.
- **`pm.exe` is locked during `uv sync`.** Stop the running `pm serve` first.
- **A face wasn't detected.** Check that **Settings → Face detection** is *Thorough* with all passes on. Then run `uv run pm ingest <folder> --rescan` to re-check photos already scanned; existing faces and names are kept. Faces found only by the extra passes show under **Faces → Possible faces**.
- **Too many "Possible faces" that aren't faces.** Mark a handful as **Not a face**. After about 5, the list sorts itself and pre-selects the likely non-faces. To stop getting them, turn passes off in Settings; *Rotated* is the main source.

## Privacy
Everything runs locally. Photos and face data never leave your computer.

## License notes
The InsightFace pretrained models are licensed for **non-commercial use only**. Fine for a family archive; replace them if this ever becomes a product.
