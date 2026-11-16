# Fictional names for code, tests and docs

Real family names never go in the repository, its history, or screenshots. Use these instead.
`tests/test_no_real_names.py` fails if a name from your private list appears in a committed file:
it reads any `Keywords.txt` under the repo and `.private-names.txt` (both gitignored), so the real
names themselves are never written down in git.

## The made-up collection

| Role in the examples | Name |
|---|---|
| Family group A (people filed as `Ashdown|<Name>`) | `Ashdown` |
| Family group B | `Marlowe` |
| Descendants of the A + B marriage | `AshdownMarlowe` |
| Someone in group A who shares the family surname | `JuliaAshdown` |
| People in group A with a different surname (married in) | `NoahWren`, `PerrySkye`, `OrlaWren`, `PipWren` |
| Person outside the families (`People|...`) | `QuinnHarlow` (use any not listed above) |
| The curator's own family (two surnames in one couple) | `Quill`, `Harcourt` |
| A "families" group of couples (`Families|...`) | `EastwickFamily` |
| Generic placeholders | `Ann Lee`, `Pat Jones`, `Jane Smith`, `Ruth Smith` |

## Rules

- Collection owner: write "the collection owner" or "the owner", never a name.
- Add new made-up names here before using them, and check they are not a real family's:
  run `uv run pytest tests/test_no_real_names.py`.
- A new real collection: add its `Keywords.txt` (or a name per line in `.private-names.txt`)
  locally. Neither file is committed.
- Test data that needs many people: generate `Person001`, `Person002`, ... instead of inventing more.
