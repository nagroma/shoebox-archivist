"""Guard: no real family names in anything that gets committed.

The names to look for are not in the repository. They are read from files that are
gitignored and exist only on a developer's machine:
  - any `Keywords.txt` under the repo (a Bridge/Lightroom keyword export), and
  - `.private-names.txt` (one name per line; surnames or full names to keep out).
With neither present the test is skipped. Use the made-up names in docs/FICTIONAL_NAMES.md.
"""
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Top-level groups the app itself uses; not family-specific.
GENERIC_GROUPS = {"attributes", "events", "families", "family", "people", "places", "subjects",
                  "scouts", "other keywords", "format", "curation", "source", "community"}
# Surnames that are also ordinary words or the standard placeholder names used in tests.
ALLOW = {"smith", "jones", "may", "jr", "sr", "short", "price", "fox", "baker", "reed", "wilson",
         "ross", "hunt", "lee", "holt", "howard", "henry", "berry", "moore", "butler", "cox",
         "ash", "cooper", "ott", "wu", "hall", "king", "young", "white", "green", "brown"}
SKIP_SUFFIX = (".lock", ".png", ".ico", ".svg", ".jpg")


def _leaves(path: Path) -> list[tuple[str, str]]:
    group, out = "", []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("\t"):
            out.append((group, line.strip()))
        elif line.strip():
            group = line.strip().strip("[]")
    return out


def _words(name: str) -> list[str]:
    return re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])", name)


def private_names() -> set[str]:
    names: set[str] = set()
    for kw in ROOT.rglob("Keywords.txt"):
        if any(p in kw.parts for p in (".venv", "node_modules")):
            continue
        leaves = _leaves(kw)
        surnames = Counter(_words(n)[-1] for _, n in leaves if len(_words(n)) >= 2)
        for group, n in leaves:
            w = _words(n)
            if len(w) >= 2 and len(n) >= 6:
                names.update({n, " ".join(w)})
        names.update(s for s, c in surnames.items() if c >= 2 and len(s) >= 4)
        names.update(g for g, _ in leaves if g.lower() not in GENERIC_GROUPS)
    extra = ROOT / ".private-names.txt"
    if extra.exists():
        names.update(l.strip() for l in extra.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#"))
    return {n for n in names if n.lower() not in ALLOW}


def test_no_real_names_in_committed_files():
    names = private_names()
    if not names:
        pytest.skip("no Keywords.txt or .private-names.txt here; nothing to check against")
    files = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard"],
                                    cwd=ROOT, text=True).split("\n")
    pattern = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in
                                                       sorted(names, key=len, reverse=True)) + r")(?![a-z])")
    hits = []
    for f in files:
        if not f or f.endswith(SKIP_SUFFIX) or f.endswith("package-lock.json"):
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if (m := pattern.search(line)):
                hits.append(f"{f}:{n}  contains a name from your private list ({len(m.group(1))} letters)")
    assert not hits, "Real names in committed files; use docs/FICTIONAL_NAMES.md:\n" + "\n".join(hits[:30])
