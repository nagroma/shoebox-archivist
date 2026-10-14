# Keyword rules (best guess — to validate with the collection owner)

These rules come from the sample sets (`photos-mt/12_*`, `photos-mt/13_*`); the keywords actually in the files are the source, not `Keywords.txt`.
They are implemented in `backend/keywords.py`. When the collection owner confirms or changes a rule, update this file and the code together.

## Where metadata lives
- Keywords are stored in each photo file's XMP:
  - `lr:hierarchicalSubject` (`Category|Name`) is the source of truth.
  - `dc:subject` holds a flat copy of the leaf names.
- The caption is `dc:description`, the date is `photoshop:DateCreated`, and the location is `Iptc4xmpCore:Location`.
- Keywords are authored in Bridge (and possibly Lightroom) alongside this app. A group that is bracketed in Bridge's keyword panel (`[Ashdown]`) is still written into files as `Ashdown|JuliaAshdown`: files are the truth, and these paths are preserved as they are.
- `Keywords.txt` (from an earlier iteration) is ignored on import; export remains for Bridge/Lightroom.

## Facets → kind
Each library has its own list of **facets**: the top-level keyword groups and what each means.
They are chosen when the library is created (a preset, plus any top-level groups found in the
photos' existing keywords) and edited at `/library`.

| Kind | Meaning |
|---|---|
| person | Keywords here are people: linked to faces and named from CamelCase (`AnnSmith` = "Ann Smith") |
| event / place / subject | Occasion / location / thing shown |
| attribute | Workflow or format tags (curation, date confidence, ...) |
| other | Anything else (community groups, sources, ...) |

- A keyword's *category* is its full parent path (`Places|USA`), so deeper trees round-trip to the files unchanged.
- Facets may be empty; a library with no person facet puts new people under `People`.
- Keywords from files that fall outside the facets keep the kind guessed from their name, else `other`; flat keywords (no group) go to `Other Keywords`.
- Libraries made before facets existed (no facets configured) keep the older built-in rules: `People` and any bracketed group are people, `Attributes`, `Events`, `Places`, `Subjects`, `Scouts`, `Families`.

## Rules
1. **Person names** are CamelCase, e.g. `JohnSmith` is displayed as "John Smith".
2. **Same name in two person groups = one person.** For example, `People|AnnBrown` and `Parish|AnnBrown` are the same person.
3. **New people** that the app creates go in the library's first `person` facet (`People` by default). In the owner's structure `People` means people *outside* the three family groups, so people in a family group keep their `Ashdown|` / `Marlowe|` / `AshdownMarlowe|` keyword and are never given a second `People|` one.
4. **Dates:**
   - `DateCreated` + `Attributes|unknowndate` → circa year (`1975~`). The day and month are treated as placeholders.
   - Without `unknowndate`, the date is used as given.
5. **Keyword naming.** A photo with exactly one person keyword and exactly one detected face gets that face *suggested* (`label_source = keyword`) for bulk confirmation. Settings → *Name from keywords* (default off) confirms it without review. Every match is suggest-then-confirm.
6. **Keyword-constrained matching.** Faces in a keyworded photo are matched only against that photo's keyword people. When exactly one face and one name are left over, the name is suggested "by elimination".

## App edits and provenance
- Keywords the app adds are listed in `sa:AddedKeywords`. The owner's own keywords are never removed silently; the UI asks first.
- The first time the app edits the caption, date or location, the previous value is saved in `sa:Original*`.
- The full fuzzy date goes in `sa:DateEDTF`. `photoshop:DateCreated` gets the plainest equivalent date.
- Bridge also keeps legacy copies of some fields: IPTC Keywords, Caption, DateCreated and SubLocation, and EXIF ImageDescription and DateTimeOriginal.
  - The app updates those copies too, so other apps don't show stale data. Their prior values are also saved in `sa:Original*`.
  - It never creates legacy fields the file didn't already have.
- **Importing new photos** reads keywords from XMP hierarchical keywords, `dc:subject`, IPTC Keywords and Windows XPKeywords.
  - A flat keyword matches an existing keyword by name, ignoring case and spaces (e.g. `Mary White` matches `People|MaryWhite`).
  - Unknown keywords go to `Other Keywords`.
- All other metadata (camera, lens, focal length…) is left untouched in the file. Photo page → File metadata shows it all.
- `pm strip` undoes every app edit in the files.
- For development, `pm baseline save` / `pm baseline restore` snapshots and restores the library.

## Questions for the collection owner
- What does **Families** mean? Couples, households, or surname groups? Should it link to people?
- Is `unknowndate` → "circa year" right, or should it be a decade or a range?
- Are names that appear in two groups always the same person?
- Which category should new people go in? (Currently `People`.)
- Is confirming single-face, single-name photos in one bulk step acceptable (auto-confirm is off by default)?
- Does the owner keep `People` for people outside the three families, or move everyone under `People` with `Family|<Name>` for the family (`pm regroup`)?
- What do primary/secondary, show/hide and question mean in his workflow?
