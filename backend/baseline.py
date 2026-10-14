"""Known-state snapshots of the library for development and testing.

The app writes keywords into the original photos. To test repeatedly:
    pm baseline save       # once: copy every photo to <data>/baseline + manifest
    pm baseline restore    # put changed photos back and start a fresh database

`pm strip` is the production-safe alternative: it removes only the keywords this
app added (listed in each file's sa:AddedKeywords) and leaves everything else.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .ingest import VOCABULARY_FILE, find_images, rel_path, sha1_of

MANIFEST = "manifest.json"


def _library_files(root: Path) -> list[Path]:
    files = find_images(root, root)
    vocab = root / VOCABULARY_FILE
    return files + [vocab] if vocab.exists() else files


def save(root: Path, dest: Path) -> int:
    """Copy the library's photos to dest (replacing any previous baseline)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    manifest = {}
    for p in _library_files(root):
        rel = rel_path(p, root)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        manifest[rel] = sha1_of(p)
    (dest / MANIFEST).write_text(json.dumps({"root": str(root), "files": manifest}, indent=1))
    return len(manifest)


def restore(root: Path, src: Path) -> tuple[int, int, list[str]]:
    """Copy back every baseline file that changed or went missing.
    Returns (restored, unchanged, files in the library that aren't in the baseline)."""
    manifest = json.loads((src / MANIFEST).read_text())["files"]
    restored = unchanged = 0
    for rel, digest in manifest.items():
        target = root / rel
        if target.exists() and sha1_of(target) == digest:
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
        restored += 1
    extra = [rel_path(p, root) for p in _library_files(root) if rel_path(p, root) not in manifest]
    return restored, unchanged, extra
