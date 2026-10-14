# Decisions and requirements

The working agreement for this project, for people and AI assistants. It records only decisions that are expensive to get wrong. Everything else is just code and can change freely.

**Rule for assistants:** if a request or idea would break something in layers 1 or 2, stop and ask. Do not work around it.

## How this file works

| Layer | What goes in it | Changing it |
|---|---|---|
| **1. Foundations** | Stack, architecture, data ownership, hard constraints. | Needs an explicit decision by the owners. Record the change in the log at the bottom. |
| **2. Guardrails** | Choices made because the alternative caused (or would cause) a problem. Each has the reason and the tripwire. | Allowed if the original reason no longer applies. Say so in the entry. |
| **3. Working defaults** | Current approach for UI, naming, layout, defaults. | Change freely when implementing. Update the line or delete it. No approval needed. |

**Does it belong here?** Add an entry only if one of these is true:
1. It shapes the architecture or would be costly to reverse (a rewrite, a data migration, a lost file).
2. We tried or considered the other choice and it hurt (bug, data loss, wasted days). Layer 2.
3. A new person or AI would plausibly "fix" it back to the wrong thing without knowing why.

If none apply, don't record it. Button colors, label wording and file layout inside a module stay out.

**Entry format (layers 1 and 2):** one short block, the *why* is mandatory.
- **Decision:** what we do.
- **Why:** the reason, including the failure it prevents.
- **Not this:** the rejected option, and what went wrong or would go wrong.
- **Revisit if:** the condition that would make it worth reopening (optional for layer 1).

Keep each entry under ~8 lines. Link to code, tests, or a doc for detail rather than repeating it. Where possible, back a guardrail with a test so it holds against any assistant.

---

## 1. Foundations

### Product
- A **local, single-user family photo library manager**: face recognition, fuzzy (EDTF) dates, photo backs. Runs on **Windows and macOS**. Photos and data stay on the user's machine.
- It works **alongside Bridge and Lightroom**, not instead of them. The collection owner keeps managing photos in Bridge. Anything the app writes must read cleanly there, and edits made there are picked up on the next import.

### Stack
- Python 3.12 with `uv`; FastAPI backend; React + TypeScript (Vite) frontend served from localhost.
- Face detection and embedding: InsightFace via ONNX Runtime, **local only** (no cloud recognition).
- Storage: SQLite, one database per library, in `<photo folder>/.shoebox/`.
- Metadata I/O: XMP read and written with pyexiv2 (`backend/xmp.py`). Keywords live in `lr:hierarchicalSubject`.
- Paths are stored relative to the library root with `/` separators, so a library moves with its folder.

### Data rules
- **The file keywords are the source of truth.** The app mirrors them. It never invents its own keyword format.
- **Provenance on every write to an original:** app-added keywords go in `sa:AddedKeywords`, edited fields keep the prior value in `sa:Original*`, and `pm strip` can undo all app edits.
- **Never touch a Lightroom catalog.**
- **People are never auto-assigned** from faces. The app suggests, a person confirms.
- **Nothing in code or tests assumes one family's names.** Collection-specific structure lives in a library's facets and vocabulary.
- Dates are EDTF text plus `date_min`/`date_max` (`backend/dates.py`).

---

## 2. Guardrails (decisions with a reason)

### Existing keywords are never lost, duplicated, or silently re-pathed
- **Decision:** every keyword in a file is kept with its exact path. Changing paths is an explicit, previewed remap with provenance (`backend/regroup.py`, `pm regroup`).
- **Why:** the owner's keyword structure is deliberate and used in Bridge. A "tidier" structure imposed by the app corrupts a catalog that took years to build.
- **Not this:** adding `People|JuliaAshdown` when `Ashdown|JuliaAshdown` exists. It creates two keywords for one person and breaks searches in Bridge.
- **Revisit if:** never as a side effect. Only through the explicit remap.

### Suggest, then confirm, for faces
- **Decision:** a match is a suggestion. The user confirms individually or in bulk. Rejected suggestions are stored as negative examples. `keyword_autoconfirm` stays off by default.
- **Why:** relatives look alike, and one wrong auto-assignment propagates into later matches and into the files.
- **Not this:** auto-assigning above a confidence threshold.

### Extra-pass faces are candidates until a person verifies them
- **Decision:** faces from an extra detection pass get `faces.candidate = 1` and stay out of clustering, matching and auto-naming until verified (`actions.verify_faces`). `backend/candidates.py` may sort and pre-select only; it never auto-hides or auto-verifies.
- **Why:** unverified false positives would pollute clusters and negative examples.

### The app's default keyword design is a proposal, not an assumption
- **Decision:** the app must work with the owner's structure unchanged (several `person` facets). The default (`People` = everyone, `Family|<Name>` = family) is offered via `pm regroup`, never assumed.
- **Why:** see the keyword guardrail above. The default does not match the existing library.

### Name changes keep the birth name in the file
- **Decision:** the keyword in the files stays under the person's primary (birth) name. Other names live in `person_names` and are shown by photo year.
- **Why:** changing the keyword would rewrite files and split a person's history across two keywords.

### Originals are changed only with the user's confirmation, and can always be undone
- **Decision:** the app never edits a photo's metadata silently. Writes are previewed and confirmed, carry provenance (`sa:AddedKeywords`, `sa:Original*`), and `pm strip` reverses them. Real use modifies originals by design; this is how it does so safely.
- **What counts as confirmation:** the UI action is the gate. Naming or confirming a face, and saving an edit, are the user's explicit act, so they write to the file immediately. Bulk or indirect changes (regroup, branch keywords) need a preview and a separate confirm. Write failures must be shown to the user, never swallowed (see BACKLOG "Fix first").
- **Development:** never experiment on the real collection. Work on a copy (`photos-mt`) and use `pm baseline save` / `pm baseline restore` to return it to a known state, so experiments leave no artifacts.
- **Why:** photos are irreplaceable, and the app is still being changed, so a bug or an experiment must not leave unexplained changes in source files.
- **Replaces:** `docs/PLAN.md` "never modify originals in the prototype". That was refined, not dropped.

> **To fill in:** guardrails are most valuable when they record a real failure. Add entries for anything that bit us (e.g. GPU/CUDA packaging problems, DB or XMP corruption cases). The reason for choosing pyexiv2 over ExifTool is not recorded anywhere; it may be a Windows/macOS packaging reason. I only wrote down guardrails whose reason is already stated in the repo.

---

## 3. Working defaults

Current approach. Change when it helps; update or delete the line.

- Settings are JSON in `settings.config`, shown at `/settings`. A function argument or flag of `None` means "use the setting".
- The family tree, branch keywords, and the other feature behavior are documented in `AGENTS.md` and `docs/USER_GUIDE.md`.
- UI layout, colors, and wording are not recorded here.

---

## Log of layer 1 and 2 changes

| Date | Change | Why |
|---|---|---|
| 2026-10-13 | File created from AGENTS.md rules and docs/PLAN.md. | Two people and two assistants direct this project; needs one shared place for settled decisions. |

## Related docs
- `AGENTS.md`: commands and short rules for assistants. Refers to this file for the reasoning.
- `docs/PLAN.md`: original plan. Where it conflicts with this file, this file wins.
- `docs/BACKLOG.md`: what to work on next. It is not a decision record.
