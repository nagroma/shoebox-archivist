"""Folder-level review and learning preferences, relative to the library root."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import db

SETTING = 'folder_scope'
FLAGS = ('learn', 'identify')


def _parent(folder: str) -> str:
    return folder.rpartition('/')[0]


@dataclass
class Policy:
    default: bool = True
    rules: dict[str, dict[str, bool]] = field(default_factory=dict)
    active: bool = False

    def enabled(self, folder: str, flag: str) -> bool:
        while True:
            rule = self.rules.get(folder, {})
            if flag in rule:
                return rule[flag]
            if not folder:
                return self.default
            folder = _parent(folder)

    def image(self, path: str, flag: str) -> bool:
        return self.enabled(_parent(path), flag)

    def choose(self, folder: str, flag: str, enabled: bool) -> None:
        self.active = True
        for name in list(self.rules):
            if not folder or name == folder or name.startswith(folder + '/'):
                self.rules[name].pop(flag, None)
                if not self.rules[name]:
                    del self.rules[name]
        if self.enabled(folder, flag) != enabled:
            self.rules.setdefault(folder, {})[flag] = enabled

    def save(self, conn) -> None:
        db.set_setting(conn, SETTING, json.dumps({'default': self.default, 'rules': self.rules}))
        conn.commit()


def load(conn) -> Policy:
    raw = db.get_setting(conn, SETTING)
    if raw is None:
        return Policy()
    value = json.loads(raw)
    return Policy(value['default'], value['rules'], active=True)


def folder_path(root: Path, relative: str) -> Path:
    from .ingest import is_ignored

    if relative and (PurePosixPath(relative).as_posix() != relative or
                     PurePosixPath(relative).is_absolute() or
                     any(p in ('.', '..') or ':' in p or '\\' in p for p in relative.split('/'))):
        raise ValueError('Choose a folder within this library')
    target = root / relative
    if target.resolve() != target or not target.is_dir() or is_ignored(Path(relative) / 'image.jpg'):
        raise ValueError('Choose an available folder within this library')
    return target


def _children(path: Path, root: Path):
    from .ingest import is_ignored

    try:
        for child in path.iterdir():
            rel = child.relative_to(root)
            if not child.is_symlink() and not child.is_junction() and not is_ignored(rel):
                yield child, rel.as_posix()
    except PermissionError:
        return


def selected_files(root: Path, start: Path, policy: Policy) -> list[Path]:
    """Enumerate only selected branches; learning-only branches need metadata, not face detection."""
    from .ingest import IMAGE_EXTS, is_ignored

    ancestors: set[str] = set()
    for folder, rule in policy.rules.items():
        if any(rule.values()):
            ancestors.add(folder)
            while folder:
                folder = _parent(folder)
                ancestors.add(folder)
    result = []
    pending = [(start, '' if start == root else start.relative_to(root).as_posix())]
    while pending:
        path, rel = pending.pop()
        active = any(policy.enabled(rel, f) for f in FLAGS)
        if not active and rel not in ancestors:
            continue
        for child, child_rel in _children(path, root):
            if child.is_dir():
                if not is_ignored(Path(child_rel) / 'image.jpg') and (active or child_rel in ancestors):
                    pending.append((child, child_rel))
            elif active and child.suffix.lower() in IMAGE_EXTS and child.is_file():
                result.append(child)
    return sorted(result)


def tree(conn) -> dict:
    """List directory names and existing index counts without reading any photo contents."""
    from .ingest import is_ignored

    root = db.library_root(conn).resolve()
    policy = load(conn)
    indexed = defaultdict(lambda: [0, 0, 0])
    for row in conn.execute('SELECT path,role,recognition_enabled,faces_scanned FROM images'):
        counts = indexed[_parent(row['path'])]
        counts[0] += 1
        if row['role'] == 'front' and row['recognition_enabled']:
            counts[1] += 1
            counts[2] += bool(row['faces_scanned'])
    result = []
    pending = [(root, '')]
    while pending:
        path, rel = pending.pop()
        files, fronts, scanned = indexed[rel]
        result.append({'path': rel, 'name': path.name or str(path), 'indexed': files, 'fronts': fronts,
                       'scanned': scanned, **{f: policy.enabled(rel, f) for f in FLAGS}})
        children = [(child, key) for child, key in _children(path, root)
                    if child.is_dir() and not is_ignored(Path(key) / 'image.jpg')]
        pending.extend(sorted(children, key=lambda pair: pair[0].name.casefold(), reverse=True))
    return {'folders': result, 'keyword_file': (root / 'Keywords.txt').is_file(),
            'scoped': policy.active}


def vocabulary_ids(conn) -> set[int] | None:
    """Choices for the keyword picker; indexed file metadata itself is always retained."""
    policy = load(conn)
    if not policy.active:
        return None
    ids = {r[0] for r in conn.execute('SELECT id FROM keywords WHERE in_vocab=1')}
    from_file = (db.library_root(conn) / 'Keywords.txt').is_file()
    for r in conn.execute('SELECT ik.keyword_id,ik.source,i.path FROM image_keywords ik JOIN images i ON i.id=ik.image_id'):
        if r['source'] == 'app' or (not from_file and policy.image(r['path'], 'learn')):
            ids.add(r['keyword_id'])
    return ids
