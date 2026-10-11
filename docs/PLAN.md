# Shoebox Archivist — Prototype Plan

> **Status (2026-10).** This is the original plan, kept for history. The prototype now covers phases 1–3 as a web app. Where it differs from this plan:
> - Metadata is read and written with **pyexiv2**, not ExifTool, directly in the photo files.
> - The originals **are** modified, but every change is tracked (`pm:` XMP namespace) and can be undone (`pm strip`).
> - Keywords, not a Lightroom catalog, seed recognition. The `.lrcat` import was not built.
> - Not built yet: MWG face-region export, Claude API transcription of backs, front/back pairing UI.
>
> Current docs: [README](../README.md), [USER_GUIDE](USER_GUIDE.md), [KEYWORD_RULES](KEYWORD_RULES.md), [AGENTS](../AGENTS.md).

## Context
A friend's family photo library (5–10k photos, on local disk, some scans over 100 years old) needs two things Lightroom does badly:
1. **Person recognition** that learns from names already tagged, with a fast UI for tagging.
2. **Fuzzy dates**: exact date, month, year, decade, "circa", or a date range.

Goal of this pass: a **prototype that proves viability** before presenting it to the friend. The prototype is a standalone app with its own database. It writes standard XMP so Lightroom can still read names and keywords. It must run on **Windows (NVIDIA GPU) and macOS**, because the two developers will co-develop it.

**Why recognition runs locally:** Claude and ChatGPT don't identify people from faces, and uploading thousands of family photos is slow and a privacy concern. Open-source face models running locally are mature, free, and fast enough on 10k photos.

## Recommended stack (cross-platform)
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12, `uv` for env/deps | Best ML ecosystem, same on Win and Mac |
| Face detect + embed | **InsightFace** (RetinaFace/SCRFD detector + ArcFace `buffalo_l`) via **ONNX Runtime** | Accuracy is close to the state of the art. ONNX runs on CUDA (Windows) and CoreML or CPU (Mac). |
| Clustering | HDBSCAN (scikit-learn) on 512-d embeddings | Groups unknown faces so you can name a whole cluster at once |
| Storage | SQLite (+ embeddings as BLOBs, brute-force cosine in NumPy) | At about 30k faces, search takes milliseconds. No vector DB needed. |
| Backend | FastAPI | Simple; serves the API and the UI on localhost |
| UI | React + TypeScript (Vite) in the browser | Rich tagging UI; same on both OSes |
| Metadata I/O | **ExifTool** (via PyExifTool) | Cross-platform; writes MWG face regions, keywords, and custom XMP |

Licensing note: InsightFace pretrained weights are licensed for **non-commercial use only**. That's fine for personal family use. If this ever becomes a product, swap in a permissively licensed model.

## Key technical challenges
1. **Historical photos degrade detection and recognition.** Black and white, faded, grainy, low resolution, small faces in group shots.
   - Mitigations: run the detector at a higher input size, tile large scans, and optionally pre-process (contrast/CLAHE). Treat old-photo accuracy as **the main viability question** and measure it separately from modern photos.
2. **Aging.** The same person at age 5 and age 80 produces different embeddings. Mitigations:
   - Keep multiple reference embeddings per person instead of one average, and match against the nearest one.
   - Use dates as a filter: skip a suggested person when the photo's date range is before their birth.
3. **Relatives look alike.** Siblings and parent/child pairs will confuse the model. So it **always suggests and never auto-assigns**: the user confirms, and a rejected suggestion is stored as a negative example.
4. **Fuzzy dates.** Store each date as:
   - `date_text` in **EDTF** (ISO 8601-2: `1923-05`, `192X`, `1925~`, `1920/1925`)
   - plus `date_min` and `date_max` (real dates for sorting and filtering) and a `precision` field.
   - The UI takes free-form input ("about 1925", "1920s", "summer 1948") and parses it.
5. **Lightroom interop.**
   - Names are written as MWG face regions plus person keywords, which Lightroom reads.
   - The fuzzy date goes in a custom XMP namespace. A best-guess `DateTimeOriginal` is written only if the user opts in.
   - Write XMP sidecars or a copy first. **Never modify originals in the prototype.**
6. **Tagging UX speed.** The main productivity win is **bulk confirm**: "these 40 faces are probably Grandma Ruth — uncheck the wrong ones." Tagging one photo at a time is the fallback.
7. **Cross-platform build.**
   - ONNX Runtime ships as a different package per OS (`onnxruntime-gpu` on Windows, `onnxruntime` on Mac). Handle it with `uv` platform markers.
   - Keep paths relative to a library root so a DB can move between machines.

## Photo backs (first-class feature)
Backs often carry handwritten names, dates, and places, which makes them the best metadata source for historical photos.

**Data model.** A `photo` is the logical item and has 1..n `images`, each with a role of `front` or `back` (`other` is allowed, e.g. an envelope).
- Faces are detected on fronts only.
- The back's text is stored as `back_text` (verbatim transcription) plus extracted **suggestions**: names, dates, places.

**Pairing fronts with backs:**
- Automatic, by filename convention (e.g. `0012.jpg` + `0012_b.jpg`, configurable) or by scan order (alternating front/back).
- Manual: a pairing UI fixes mistakes.

**Reading the handwriting.** Old cursive is hard for local OCR.
- Recommended: send **backs only** to the Claude API for transcription and structured extraction. Backs contain no faces, so the privacy cost is low, and modern vision LLMs read old handwriting far better than local OCR.
- Local fallback: Apple Vision on Mac, or manual typing.
- A human always reviews the result before it is accepted.

**Using the extracted data:**
- The extracted date pre-fills the fuzzy-date field (e.g. "Xmas 1931" → `1931-12`).
- Extracted names become person suggestions for that photo, which raises the confidence of matching faces.
- "L to R: Ruth, John, Mary" maps to face boxes sorted left to right, as a one-click suggestion.

**Export:**
- The transcription goes to `dc:description`, or to a custom XMP field.
- The back image's path goes in the custom namespace.

## Importing existing Lightroom metadata
Assumes **Lightroom Classic**, whose catalog is a local `.lrcat` file (to be confirmed with the friend). Lightroom CC (cloud) would need its API instead.

**Primary path: read the `.lrcat` directly.** It is a SQLite database, so Python's `sqlite3` reads it with no Lightroom install.
- Always work on a **copy**, opened read-only. Never write to the catalog.
- It captures everything, including metadata never saved to XMP, collections, and hierarchical keywords.
- Expected sources (verify the schema against the friend's catalog, since it varies by Lightroom version):

| Data | Lightroom tables |
|---|---|
| Files and paths | `AgLibraryRootFolder`, `AgLibraryFolder`, `AgLibraryFile` |
| Images, ratings, flags, capture date | `Adobe_images` |
| Keywords (hierarchical), including person keywords | `AgLibraryKeyword`, `AgLibraryKeywordImage` |
| Face regions and their names | `AgLibraryFace`, plus the face→keyword link table |
| Caption, title, location | `AgLibraryIPTC`, `AgHarvestedIptcMetadata` |
| Collections | `AgLibraryCollection*` |

**Fallback path: XMP.** In Lightroom, run "Save Metadata to Files" (Ctrl/Cmd+S). Our ingest then reads the XMP and embedded metadata through ExifTool. This also covers photos that were never in Lightroom.

**Mapping into our model:**
- Names on faces become **confirmed** faces. This is the big win: they are ready-made training labels, so recognition works from day one.
- Person keywords on photos with no face region become "person is in this photo" hints. The face matcher then only has to work out which face is that person.
- Dates:
  - Import the Lightroom capture date with `precision = unknown`.
  - Detect the friend's **placeholder conventions** (e.g. everything dated Jan 1, a time of 00:00, or keywords like "1920s") and convert them to fuzzy dates.
  - Each conversion is shown in a review list, never silently applied.
- Keep the Lightroom image id on every photo, so a later re-import can update records instead of duplicating them.

## Phases (each ends with a go/no-go check)

### Phase 1 — Recognition spike (CLI only, ~days)
- `ingest <folder>`: walk the folder, hash files, and pair backs with fronts using the filename rule. Detect faces on fronts only, and save face crops and embeddings to SQLite.
- `import-lrcat <copy.lrcat>`: import paths, keywords, faces, dates, and captions. The names on faces become confirmed labels, which seed recognition.
- `cluster`: run HDBSCAN and generate a static HTML report with one face grid per cluster.
- `label` (minimal): name clusters, then rerun matching on the rest and report the suggestions.
- **Gate:** on a test set of about 300 photos (half historical), measure detection recall and how pure the clusters are. Also measure top-1 suggestion accuracy after labeling 3–5 faces per person.

### Phase 2 — Tagging UI
- **People view:** each person's faces, plus "suggested" faces to confirm or reject in bulk.
- **Unknown clusters queue:** name a cluster, merge it into an existing person, or ignore it (strangers, faces in paintings).
- **Photo view:** face boxes, name autocomplete per box, manually draw a missed face, and a "who's in this photo" list.
- Tagging is keyboard-driven: Y/N/next.

### Phase 3 — Fuzzy dates and core metadata
- Date field with the EDTF parser, and sort/filter by range.
- Person records with birth and death years, used to filter suggestions.
- Location and other fields: deferred until the metadata spec arrives.
- Backs:
  - Pairing (automatic and manual).
  - A side-by-side front/back view with an editable transcription.
  - Claude API transcription and extraction, feeding the date and person suggestions.
- **Gate:** transcription accuracy on about 30 real backs.

### Phase 4 — XMP export (standards-based, app-agnostic)
- Export face regions (MWG), person keywords, and dates through ExifTool.
- Lightroom is **not required** for the prototype. Verify the export with an ExifTool read-back. Then open the files in a free viewer that reads MWG regions (e.g. digiKam), and in LightCraft if useful.
- The friend can check Lightroom compatibility later, since he presumably has Lightroom.

LightCraft (github.com/storytold/lightcraft) is an optional viewer/editor, not the foundation:
- It is alpha, has no face recognition yet, and doesn't support fuzzy dates.
- It is Rust/egui with no plugin API, so it can't host our tagging UI.
- It does read and write XMP sidecars, so it can sit alongside our app.

## Proposed project layout
```
shoebox-archivist/
  pyproject.toml          # uv, platform-specific onnxruntime
  backend/
    ingest.py  faces.py  cluster.py  match.py  dates.py  xmp.py
    db.py (SQLite schema)  api.py (FastAPI)
  frontend/  (Vite + React + TS)
  tests/     (dates parser, matching thresholds)
  AGENTS.md / CLAUDE.md   # shared conventions for both devs' AI assistants
```
Core tables:
- `photos`: date_text, date_min, date_max, precision, back_text
- `images`: photo_id, role (front / back / other), path, hash
- `suggestions`: photo_id, kind (name / date / place), value, source (back OCR / face match), status
- `faces`: image_id, bbox, embedding, person_id, status (suggested / confirmed / rejected)
- `people`: name, birth year, death year
- `rejections`: face_id, person_id

## Verification
- **Phase 1:** run on the 300-photo test set and record the accuracy numbers in a short results note. That note is the viability evidence for the friend.
- Unit tests for the EDTF date parser (`1920s`, `c. 1925`, `May 1923`, `1920-1925`).
- Run on Windows (CUDA) and on a Mac (CoreML/CPU) to confirm portability early.
- **Phase 4:** read the written XMP back with ExifTool and confirm the regions, keywords, and EDTF date are there. Open the files in digiKam and check that the face boxes show.

## Needed from the friend early
These are small, but they unblock the Lightroom import:
- A copy of the `.lrcat` (no photos needed).
- About 300 sample photos with their backs.
- Which Lightroom version he uses, and how he currently records uncertain dates.

## Open items (not blocking Phase 1)
- The full metadata field list (the friend will supply it).
- Scan workflow: how backs are named or ordered by the friend's scanner, which determines the auto-pairing rule.
- Duplicate handling: the same print scanned twice, or the same photo in different crops.
- How the two developers sync library DBs, if they ever need to.
