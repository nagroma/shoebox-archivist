# Backlog

## Where we left off (2026-10-11)
- Working libraries: `photos-am` (the curator's family, Morgan / Mulligan; fresh facets) and `photos-mt` (the friend's, legacy keyword set). Both are gitignored; app data lives in `<folder>/.shoebox/`.
- Built this session: libraries created from the UI, facets, curator, aliases + dated names, family links + tree, branch keywords, keyword cleanup, damaged-metadata fallback.
- Next candidates: the "How is X related to you?" prompt, former partner, branch-name override, a browser pass over the Library / Tree pages, GEDCOM import.
- Restart the app: `cd frontend && npm run build`, then `uv run pm serve` (opens the last library). If `pm` is not found after moving the folder, run `uv sync`.

Future work, not scheduled. Move an item to PLAN.md or delete it when done. Newest ideas go at the bottom of each section.

## Names and keywords
- Export aliases to Bridge/Lightroom as keyword synonyms, so searching a married name finds the person. Lightroom's Keywords.txt synonym format needs verifying first.
- Rename a keyword in the files (record the old one in `pm:OriginalKeywords`, support `pm strip`).
- Show the dated alias (not the keyword name) on photo keyword chips.
- Make the "unknown date -> circa year" placeholder rule configurable per library.
- Generic KEYWORD_STRATEGY guide (current one is one collection's example).

## Family tree
- Done: parent/partner links, derived siblings and curator-relative labels (People page > Family).
- Done: branch keywords (Tree page). Open: override a branch name (e.g. a double-barrelled or changed surname), run it automatically after link edits, `Family` facet auto-created in new libraries.
- "How is X related to you?" prompt when a new person is named.
- Done: visual tree (Tree tab) and family photo filter. Still open: side-of-family and branch keywords written to photos, printing/exporting the tree, collapsing large trees.
- Gendered labels (Mother/Father, Aunt/Uncle) if a gender or title field is ever added.
- Half-siblings, step-parents, adoption (all treated the same as parents for now).
- Derived branch, generation and side keywords.
- Optional GEDCOM import.

## People and faces
- Former partner (end of a partnership): a link flag/end year so ex-partners stop sharing branch keywords and show as 'former partner'.
- Pets: tag as a non-person keyword; detect dog/cat faces rather than ignoring them.
- Ignore many small background faces at once (size threshold, or ignore a whole cluster). Low priority: per-face Ignore works well enough.

## Libraries
- UI route back to a legacy (PM_DATA) library.
- Browser test pass of the Library page (create / open / reset).
- Initialization test of an existing library with keywords already in the files (re-init photos-am after a working period).
