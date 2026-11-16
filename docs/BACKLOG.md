# Backlog

Open work only. Delete an item when it is done (move it to PLAN.md if it needs a design). Newest ideas at the bottom of each section.

## Where we left off (2026-10-13)
- Ready for the collection owner's review; the browser pass for this session is considered done. Keep an eye out for rough edges on the Library page (setup screen, "New keyword groups", "Family-name groups", reset) and the likely-match cards when the owner tries them.
- **Bridge check** still to do by hand: open a file the app wrote (a regroup on a *copy*) in Bridge/Lightroom and confirm the keywords read cleanly.
- Real names: guarded by `tests/test_no_real_names.py` and `docs/FICTIONAL_NAMES.md`. Commit `02fab69` (public) still has a few real family names; the risk is judged low, so history is not rewritten. Just don't add more.
- Next: step-by-step migration guide for the owner (backup, preview, convert, `pm strip` to undo), written from the rehearsal on a copy.
- Restart the app: F5 in VS Code (builds the UI), or `uv run pm serve` after `npm run build` in `frontend`. If `pm` is not found after moving the folder, run `uv sync`.

## Fix first (next session)
- **File-write errors are swallowed.** `actions.add_photo_keyword` / `remove_photo_keyword` print to stderr and return False; `assign`, `reject`, `ignore` (via `_sync_keywords`), `update_photo` and batch edit don't tell the user a file couldn't be written (read-only, locked, damaged metadata block). Report failures to the UI per photo (which file, why), keep the DB and file consistent, and never claim "Named" when the keyword didn't reach the file. Add tests (read-only file, damaged XMP).

- **Backup before first write.** If a library has no baseline/backup, offer to make one before the first write to the photo files (protects dev experiments; for a real user, a "back up your photos first" prompt). Not built yet.

## Names and keywords
- Export aliases to Bridge/Lightroom as keyword synonyms, so searching a married name finds the person. Lightroom's Keywords.txt synonym format needs verifying first.
- Rename a keyword in the files (record the old one in `sa:OriginalKeywords`, support `pm strip`).
- Show the dated alias (not the keyword name) on photo keyword chips.
- Make the "unknown date -> circa year" placeholder rule configurable per library.
- Generic keyword-strategy guide (the local KEYWORD_STRATEGY.md is one collection's example and is not committed).

## Libraries
- General remap utility for explicit keyword-path patterns beyond family-name groups (dry-run, provenance, previewed and confirmed).
- Merge-duplicates action for libraries that already have the same person under two groups.
- After `pm strip` restores removed keywords, the DB needs a re-ingest to see them again.
- Regroup rule is provisional (every person in the group gets `Family|<Group>`). If the owner wants otherwise, make the family keyword opt-in per person.
- Initialization test of an existing library with keywords already in the files (re-init the sample library after a working period).
- The setup screen only hints that a group looks like people; consider reading the keyword structure from the owner's feedback.

## Family tree
- **Rethink `actions.auto_branches`** together with the Family vs. family-name-group (`Ashdown|`, `Marlowe|`, ...) keyword question. Today, once the first branch sync is confirmed, every naming click or keyword edit can add or remove `Family|<Branch>` keywords on that photo without a further prompt. Decide whether branch keywords should exist at all in the owner's structure, and if so, whether they need a visible pending/confirm step. Until decided, don't extend it.
- Branch keywords: override a branch name (double-barrelled or changed surname); `Family` facet auto-created in new libraries.
- "How is X related to you?" prompt when a new person is named.
- Side-of-family and generation keywords written to photos; printing/exporting the tree; collapsing large trees.
- Picking one relationship label per person would need a gender or title field.
- Half-siblings, step-parents, adoption (all treated the same as parents for now).
- Former partner (end of a partnership): flag/end year so ex-partners stop sharing branch keywords.
- Optional GEDCOM import.

## Scanning
- Confirm the FastFoto naming (`name.jpg`, `name_a.jpg`, `name_b.jpg`) on real output and that `pm ingest` merges earlier separate imports.
- Other scanners' naming schemes, if they turn up.

## People and faces
- Pets: tag as a non-person keyword; detect dog/cat faces rather than ignoring them.
- Ignore many small background faces at once (size threshold, or a whole cluster). Low priority.
- Tune `cluster_merge_threshold` and `neighbour_threshold` on the owner's large folder (about 1,300 unnamed faces); the sample is too small to judge.
