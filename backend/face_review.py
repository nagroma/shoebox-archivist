"""Select files for the Faces view without changing grouping or recognition."""
from __future__ import annotations

import json
from collections import defaultdict

from . import db, folders, variations

SETTING = 'faces.view'


def plan(conn, preference=None):
    cfg = variations.load(conn)
    types = {t['suffix']: t for t in cfg['types']}
    front_types = [t for t in cfg['types'] if t['role'] == 'front' and t['suffix']]
    front_suffixes = {t['suffix'] for t in front_types}
    policy = folders.load(conn)
    groups = defaultdict(list)
    available = {}
    for r in conn.execute('SELECT id,photo_id,path,role,variation,variation_label,faces_scanned FROM images ORDER BY path,id'):
        if not policy.image(r['path'], 'identify'):
            continue
        if r['variation_label']:
            # Respect applied groups (including manual separations), even when grouping is paused.
            key = ('photo', r['photo_id'])
            suffix, label, role = r['variation'], r['variation_label'], r['role']
        else:
            # Older libraries can use the view without accepting a database regrouping.
            item = variations.classify(r['path'], cfg)
            key = ('filename', item['key'])
            if r['role'] == 'back' and (item['issue'] or item['role'] != 'back') and not cfg['enabled']:
                suffix, label, role = item['suffix'] or '_b', 'Back', 'back'
            elif item['issue']:
                suffix, label, role = '', 'Original front', 'front'
            else:
                suffix, label, role = item['suffix'], item['label'], item['role']
        available.setdefault(suffix, {**types.get(suffix, {'suffix': suffix, 'label': label, 'role': role}), 'files': 0})
        available[suffix]['files'] += 1
        groups[key].append((r, suffix, role))

    if preference is None:
        preference = json.loads(db.get_setting(conn, SETTING) or '{}')
    preferred = preference.get('preferred')
    if preferred is not None and preferred not in front_suffixes | {''}:
        preferred = None
    # Null follows the library's default; an empty string explicitly uses originals.
    effective = cfg['recognition'] if preferred is None else preferred
    also_show = list(dict.fromkeys(s for s in preference.get('also_show', []) if s in available or s in types))
    extras = set(also_show)
    selected = set()
    fallback = unscanned = 0
    for group in groups.values():
        fronts = [(r, s) for r, s, role in group if role == 'front']
        preferred_files = [r for r, s in fronts if s == effective] if effective else []
        originals = [r for r, s in fronts if not s]
        main = preferred_files or originals
        if effective and not preferred_files and originals:
            fallback += 1
        # Pick one main file deterministically, even if the same version has several formats.
        visible = {main[0]['id']} if main else set()
        visible.update(r['id'] for r, s, _ in group if s in extras)
        selected.update(visible)
        unscanned += sum(r['id'] in visible and not r['faces_scanned'] for r, _ in fronts)
    settings = {'preferred': preferred, 'also_show': also_show, 'effective': effective,
                'default_preferred': cfg['recognition'], 'front_types': front_types,
                'available': sorted(available.values(), key=lambda t: (t['suffix'] != '', t['suffix'])),
                'fallback': fallback, 'unscanned': unscanned}
    return selected, settings
