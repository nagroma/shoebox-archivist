"""Library-specific filename conventions and non-destructive grouping previews."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import defaultdict
from pathlib import Path

from . import db

LOCK = threading.RLock()
SETTING = 'variations.config'
DEFAULT = {'enabled': False, 'pattern': 'suffix', 'preferred': '_a', 'recognition': '_a',
           'types': [{'suffix': '', 'label': 'Original front', 'role': 'front'},
                     {'suffix': '_a', 'label': 'Corrected front', 'role': 'front'},
                     {'suffix': '_b', 'label': 'Back', 'role': 'back'}]}


def load(conn):
    return json.loads(db.get_setting(conn, SETTING) or json.dumps(DEFAULT))


def validate(value):
    if not isinstance(value, dict) or value.get('pattern') not in ('suffix', 'serial'):
        raise ValueError('Choose a filename convention')
    types = value.get('types', [])
    if not isinstance(types, list) or not types or len(types) > 100:
        raise ValueError('Define at least one variation type (up to 100)')
    seen = set()
    for t in types:
        if not isinstance(t, dict) or not all(k in t for k in ('suffix', 'label', 'role')):
            raise ValueError('Each variation needs a suffix, name and role')
        suffix = t.get('suffix', '')
        if not isinstance(suffix, str) or any(c in suffix for c in '/\\\n\r\t'):
            raise ValueError('Suffixes cannot contain folder separators or newlines')
        if suffix.casefold() in seen:
            raise ValueError('Each suffix must be unique, ignoring case')
        seen.add(suffix.casefold())
        if not isinstance(t.get('label'), str) or not t['label'].strip() or t.get('role') not in ('front', 'back', 'other'):
            raise ValueError('Give each variation a name and a role')
    fronts = {t['suffix'] for t in types if t['role'] == 'front'}
    if not fronts or value.get('preferred') not in fronts or value.get('recognition') not in fronts:
        raise ValueError('Choose a front variation for display and face recognition')
    return {'enabled': bool(value.get('enabled')), 'pattern': value['pattern'],
            'preferred': value['preferred'], 'recognition': value['recognition'], 'types': types}


def classify(path: str, cfg: dict):
    p = Path(path)
    stem = p.stem
    types = sorted(cfg['types'], key=lambda t: -len(t['suffix']))
    selected = None
    if cfg['pattern'] == 'serial':
        selected = next((t for t in types if t['suffix'] and stem.casefold().endswith(t['suffix'].casefold())
                         and re.search(r'\d$', stem[:-len(t['suffix'])])), None)
        m = re.match(r'^(.*\d)(\D*)$', stem)
        if selected:
            suffix = selected['suffix']
            base = stem[:-len(suffix)]
        elif m:
            base, suffix = m.groups()
            selected = next((t for t in types if t['suffix'].casefold() == suffix.casefold()), None)
        else:
            return {'key': f'unmatched:{path}', 'suffix': '', 'label': 'Unmatched filename',
                    'role': 'front', 'issue': 'No serial number; kept separate'}
    else:
        selected = next((t for t in types if t['suffix'] and stem.casefold().endswith(t['suffix'].casefold())), None)
        suffix = selected['suffix'] if selected else ''
        base = stem[:-len(suffix)] if suffix else stem
        # Unknown trailing suffixes following a serial are not silently treated as originals.
        m = re.match(r'^(.*\d)(\D+)$', stem)
        if selected is None and m:
            base, suffix = m.groups()
        elif selected is None:
            selected = next((t for t in types if t['suffix'] == ''), None)
    if selected is None or not base:
        return {'key': f'unmatched:{path}', 'suffix': suffix, 'label': 'Unmapped variation',
                'role': 'front', 'issue': f'Unmapped suffix {suffix!r}; kept separate'}
    return {'key': f'{p.parent.as_posix()}/{base.casefold()}', 'suffix': selected['suffix'],
            'label': selected['label'], 'role': selected['role'], 'issue': None}


def _primary(members, preferred):
    return min(members, key=lambda m: (m['role'] != 'front', m['suffix'] != preferred,
                                       m['path'].casefold(), m['id']))


def preview(conn, cfg=None, overrides=None):
    cfg = validate(cfg or load(conn))
    overrides = overrides if overrides is not None else dict(conn.execute(
        'SELECT image_id, group_key FROM image_group_overrides'))
    rows = [dict(r) for r in conn.execute('SELECT * FROM images ORDER BY path')]
    if any(i not in {r['id'] for r in rows} or not isinstance(key, str) or not key.strip() for i, key in overrides.items()):
        raise ValueError('Manual groups need existing images and non-empty names')
    groups = defaultdict(list)
    for row in rows:
        item = classify(row['path'], cfg)
        if row['id'] in overrides:
            item['key'] = 'manual:' + overrides[row['id']]
            item['issue'] = None
        groups[item['key']].append({**row, **item})
    out = []
    for key, members in groups.items():
        primary = _primary(members, cfg['preferred'])
        recognition = _primary(members, cfg['recognition'])
        duplicates = len({(m['suffix'], Path(m['path']).suffix.casefold()) for m in members}) != len(members)
        source_ids = sorted({m['photo_id'] for m in members})
        metadata = [dict(r) for r in conn.execute(
            'SELECT * FROM photos WHERE id IN (' + ','.join('?' for _ in source_ids) + ')', source_ids)]
        conflicts = [k for k in ('date_text', 'caption', 'location', 'notes', 'back_text')
                     if len({r[k] for r in metadata if r[k]}) > 1]
        out.append({'key': key, 'members': members, 'primary_id': primary['id'],
                    'recognition_id': recognition['id'] if recognition['role'] == 'front' else None,
                    'issues': [m['issue'] for m in members if m['issue']] +
                              (['Multiple files have the same suffix and extension; review this group'] if duplicates else []),
                    'metadata_conflicts': conflicts, 'metadata_versions': metadata})
    signature = hashlib.sha256(json.dumps({'config': cfg, 'overrides': sorted(overrides.items()),
                                          'groups': out}, sort_keys=True).encode()).hexdigest()
    return {'config': cfg, 'groups': out, 'token': signature, 'files': len(rows)}


def apply(conn, cfg, token, overrides=None):
    """Explicit preview acceptance. Only database relationships change, never files."""
    cfg = validate(cfg)
    plan = preview(conn, cfg, overrides)
    if token != plan['token']:
        raise ValueError('The library changed. Preview the groups again before applying.')
    if not cfg['enabled']:
        raise ValueError('Enable the filename convention before applying groups')
    # The API saves a SQLite backup before a manually accepted regrouping.
    # Original photo fields are also retained per image for later splits.
    used = set()
    for g in plan['groups']:
        for m in g['members']:
            ph = dict(conn.execute('SELECT * FROM photos WHERE id = ?', (m['photo_id'],)).fetchone())
            conn.execute('INSERT OR IGNORE INTO image_photo_history(image_id,metadata) VALUES (?,?)',
                         (m['id'], json.dumps(ph)))
    for g in plan['groups']:
        primary = next(m for m in g['members'] if m['id'] == g['primary_id'])
        target = primary['photo_id']
        sources = {m['photo_id'] for m in g['members']}
        if target in used:
            saved = json.loads(conn.execute('SELECT metadata FROM image_photo_history WHERE image_id = ?',
                                            (primary['id'],)).fetchone()[0])
            cols = [k for k in saved if k not in ('id', 'lr_image_id')]
            target = conn.execute('INSERT INTO photos(' + ','.join(cols) + ') VALUES (' +
                                  ','.join('?' for _ in cols) + ')', [saved[k] for k in cols]).lastrowid
        used.add(target)
        for source in sources:
            if source == target:
                continue
            old = dict(conn.execute('SELECT * FROM photos WHERE id = ?', (source,)).fetchone())
            for field, val in old.items():
                if field not in ('id', 'lr_image_id') and val is not None:
                    conn.execute(f'UPDATE photos SET {field} = COALESCE({field}, ?) WHERE id = ?', (val, target))
            conn.execute('INSERT OR IGNORE INTO photo_keyword_intents SELECT ?,keyword_id '
                         'FROM photo_keyword_intents WHERE photo_id = ?', (target, source))
        for m in g['members']:
            conn.execute('UPDATE images SET photo_id=?, role=?, variation=?, variation_label=?, '
                         'is_primary=?, recognition_enabled=? WHERE id=?',
                         (target, m['role'], m['suffix'], m['label'], int(m['id'] == g['primary_id']),
                          int(m['id'] == g['recognition_id']), m['id']))
        for source in sources - {target}:
            if not conn.execute('SELECT 1 FROM images WHERE photo_id = ?', (source,)).fetchone():
                conn.execute('UPDATE suggestions SET photo_id=? WHERE photo_id=?', (target, source))
                conn.execute('DELETE FROM photos WHERE id=?', (source,))
    if overrides is not None:
        conn.execute('DELETE FROM image_group_overrides')
        conn.executemany('INSERT INTO image_group_overrides(image_id,group_key) VALUES (?,?)', overrides.items())
    db.set_setting(conn, SETTING, json.dumps(cfg))
    from . import sharing
    sharing.rebuild_union(conn)
    conn.commit()
    return {'groups': len(plan['groups']), 'files': plan['files']}


def regroup_import(conn):
    cfg = load(conn)
    if cfg['enabled']:
        p = preview(conn, cfg)
        return apply(conn, cfg, p['token'])
    return None
