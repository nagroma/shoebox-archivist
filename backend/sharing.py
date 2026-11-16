"""Keyword scopes, actual per-file metadata, preserved exceptions and review-only audits."""
from __future__ import annotations

import json

from . import db, keywords, xmp

SETTING = 'sharing.rules'
DEFAULT = {'rules': []}
MODES = {'all', 'fronts', 'backs', 'current', 'ask', 'selected', 'one'}


def load(conn):
    data = json.loads(db.get_setting(conn, SETTING) or json.dumps(DEFAULT))
    return {'rules': data['rules']}


def validate_scope(scope):
    if not isinstance(scope, dict) or scope.get('mode') not in MODES:
        raise ValueError('Choose where the keyword applies')
    suffixes = scope.get('suffixes', [])
    if not isinstance(suffixes, list) or any(not isinstance(s, str) for s in suffixes):
        raise ValueError('Choose filename variations')
    if scope['mode'] == 'selected' and not suffixes:
        raise ValueError('Select at least one variation')
    return {'mode': scope['mode'], 'suffixes': list(dict.fromkeys(suffixes))}


def save(conn, data):
    rules = []
    seen = set()
    for rule in data.get('rules', []):
        target, path = rule.get('target'), rule.get('path', '').strip()
        if target not in ('hierarchy', 'keyword') or not path or (target, path) in seen:
            raise ValueError('Each rule needs a unique hierarchy or full keyword path')
        seen.add((target, path))
        rules.append({'target': target, 'path': path, 'scope': validate_scope(rule.get('scope'))})
    result = {'rules': rules}
    db.set_setting(conn, SETTING, json.dumps(result))
    conn.commit()
    return result


def inventory(conn):
    """Refresh new/changed files; read errors must never look like empty keywords."""
    errors = []
    root = db.library_root(conn)
    metadata = []
    index_current = db.get_setting(conn, 'sharing.index_version') == '2'
    for r in conn.execute('SELECT id,path,keywords_indexed,keyword_stamp FROM images').fetchall():
        try:
            stat = (root / r['path']).stat()
            stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
            if index_current and r['keywords_indexed'] and r['keyword_stamp'] == stamp:
                continue
            xmp.read_all(root / r['path'])
            info = xmp.read(root / r['path'])
            metadata.append((r, info, stamp))
            for value in info.keywords:
                category, name = keywords.split(value)
                if category:
                    keywords.ensure(conn, category, name)
        except Exception as e:
            conn.execute('UPDATE images SET keywords_indexed=0 WHERE id=?', (r['id'],))
            errors.append({'image_id': r['id'], 'path': r['path'], 'error': str(e)})
    for r, info, stamp in metadata:
        values = list(info.keywords)
        segments = {s for kw in values for s in kw.split('|')}
        values += [k for k in dict.fromkeys(info.flat + info.other) if k not in segments]
        conn.execute('DELETE FROM image_keywords WHERE image_id=?', (r['id'],))
        for value in values:
            kid = keywords.resolve(conn, value)
            conn.execute('INSERT OR REPLACE INTO image_keywords(image_id,keyword_id,source,hierarchical) VALUES (?,?,?,?)',
                         (r['id'], kid, 'app' if value in info.app_added else 'file', int(value == keywords.path_of(conn, kid))))
        conn.execute('UPDATE images SET keywords_indexed=1, keyword_stamp=? WHERE id=?', (stamp, r['id']))
    rebuild_union(conn)
    db.set_setting(conn, 'sharing.index_version', '2')
    conn.commit()
    return errors


def rebuild_union(conn, photo_id=None):
    args = (photo_id,) if photo_id is not None else ()
    # Don't erase a legacy union until every physical file has been indexed.
    photos = conn.execute('SELECT id FROM photos' + (' WHERE id=?' if photo_id is not None else ''), args).fetchall()
    for (pid,) in photos:
        if conn.execute('SELECT 1 FROM images WHERE photo_id=? AND keywords_indexed=0', (pid,)).fetchone():
            continue
        conn.execute('DELETE FROM photo_keywords WHERE photo_id=?', (pid,))
        conn.execute("INSERT INTO photo_keywords(photo_id,keyword_id,source) "
                     "SELECT ?,ik.keyword_id,CASE WHEN SUM(ik.source='file')>0 THEN 'file' ELSE 'app' END "
                     'FROM image_keywords ik JOIN images i ON i.id=ik.image_id WHERE i.photo_id=? '
                     'GROUP BY ik.keyword_id', (pid, pid))


def resolve_scope(conn, photo_id, kid, image_ids=None, *, include_local=True):
    local = None
    if include_local and image_ids is None:
        local = conn.execute('SELECT s.scope FROM photo_keyword_scopes s JOIN images i ON i.id=s.anchor_image_id '
                             'WHERE i.photo_id=? AND s.keyword_id=? ORDER BY i.is_primary DESC,i.id LIMIT 1',
                             (photo_id, kid)).fetchone()
    elif include_local:
        local = conn.execute('SELECT scope FROM photo_keyword_scopes WHERE keyword_id=? AND anchor_image_id IN (' +
                             ','.join('?' for _ in image_ids) + ') ORDER BY anchor_image_id=? DESC,anchor_image_id LIMIT 1',
                             [kid, *image_ids, image_ids[0]]).fetchone()
    if local:
        return json.loads(local[0]), 'This photograph'
    k = conn.execute('SELECT * FROM keywords WHERE id=?', (kid,)).fetchone()
    if not k:
        raise ValueError('No such keyword')
    path = f"{k['category']}|{k['name']}"
    rules = load(conn)['rules']
    exact = next((r for r in rules if r['target'] == 'keyword' and r['path'] == path), None)
    ancestors = [r for r in rules if r['target'] == 'hierarchy' and
                 (path == r['path'] or k['category'] == r['path'] or k['category'].startswith(r['path'] + '|'))]
    rule = exact or (max(ancestors, key=lambda r: len(r['path'])) if ancestors else None)
    if rule:
        return rule['scope'], ('Keyword rule' if exact else 'Hierarchy: ' + rule['path'])
    return {'mode': 'all', 'suffixes': []}, 'Default'


def targets(images, scope, current_ids=(), active_image=None):
    mode = scope['mode']
    if mode == 'all':
        return {i['id'] for i in images}
    if mode == 'fronts':
        return {i['id'] for i in images if i['role'] == 'front'}
    if mode == 'backs':
        return {i['id'] for i in images if i['role'] == 'back'}
    if mode == 'selected':
        return {i['id'] for i in images if i['variation'] in scope.get('suffixes', [])}
    return set(current_ids) | ({active_image} if active_image is not None else set())


def _images(conn, pid):
    return [dict(r) for r in conn.execute('SELECT * FROM images WHERE photo_id=? ORDER BY is_primary DESC,role=\'front\' DESC,id', (pid,))]


def write_one(conn, image_id, kid, present, only_app=True):
    image = conn.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone()
    if not image:
        raise ValueError('No such image')
    path = db.library_root(conn) / image['path']
    # Read again immediately before editing; don't claim success on unreadable/stale metadata.
    xmp.read_all(path)
    value = keywords.path_of(conn, kid)
    info = xmp.read(path)
    exists = value in info.keywords or (value.split('|')[-1] in info.flat + info.other and
              any(r[0] == kid for r in conn.execute('SELECT keyword_id FROM image_keywords WHERE image_id=?', (image_id,))))
    source = conn.execute('SELECT source FROM image_keywords WHERE image_id=? AND keyword_id=?', (image_id, kid)).fetchone()
    if present:
        xmp.add_keywords(path, [value])
        check = xmp.read(path)
        if value not in check.keywords:
            raise ValueError('The keyword could not be verified after writing')
        conn.execute('INSERT OR REPLACE INTO image_keywords(image_id,keyword_id,source,hierarchical) VALUES (?,?,?,1)',
                     (image_id, kid, 'app' if value in check.app_added else 'file'))
    else:
        if only_app and ((source and source[0] != 'app') or (exists and value not in info.app_added)):
            return False
        xmp.remove_keywords(path, [value], only_app_added=only_app)
        check = xmp.read(path)
        if value in check.keywords:
            raise ValueError('The keyword is still in the file')
        # Flat-only original keywords need an explicit, provenance-preserving removal.
        leaf = xmp.leaf(value)
        if not only_app and exists and leaf in check.flat + check.other and not any(xmp.leaf(k) == leaf for k in check.keywords):
            xmp.remove_flat_keyword(path, leaf)
        conn.execute('DELETE FROM image_keywords WHERE image_id=? AND keyword_id=?', (image_id, kid))
    stat = path.stat()
    conn.execute('UPDATE images SET keywords_indexed=1,keyword_stamp=? WHERE id=?', (f'{stat.st_mtime_ns}:{stat.st_size}', image_id))
    rebuild_union(conn, image['photo_id'])
    # Commit each successful file: a later failure is reported, never rolled back only in SQLite.
    conn.commit()
    return True


def add(conn, photo_id, kid, active_image=None, scope=None):
    errors = inventory(conn)
    images = _images(conn, photo_id)
    if not images:
        raise ValueError('No images in this photograph')
    if any(e['image_id'] in {i['id'] for i in images} for e in errors):
        raise ValueError('A file in this photograph cannot be read; review the import errors')
    requested_image = active_image
    active_image = active_image or images[0]['id']
    if active_image not in {i['id'] for i in images}:
        raise ValueError('Choose an image in this photograph')
    if scope is not None:
        set_photo_scope(conn, photo_id, kid, scope)
    scope, _ = resolve_scope(conn, photo_id, kid)
    conn.execute('INSERT OR IGNORE INTO photo_keyword_intents VALUES (?,?)', (photo_id, kid))
    conn.commit()
    current = [r[0] for r in conn.execute('SELECT ik.image_id FROM image_keywords ik JOIN images i ON i.id=ik.image_id '
                                        'WHERE i.photo_id=? AND ik.keyword_id=?', (photo_id, kid))]
    wanted = targets(images, scope, current, active_image if scope['mode'] == 'current' else None)
    if scope['mode'] == 'ask':
        return False  # intent appears as "choose scope" in review, no arbitrary metadata write
    exceptions = dict(conn.execute('SELECT e.image_id,e.present FROM image_keyword_exceptions e JOIN images i '
                                   'ON i.id=e.image_id WHERE i.photo_id=? AND e.keyword_id=?', (photo_id, kid)))
    if scope['mode'] == 'one':
        reserved = set(current) | {image_id for image_id, present in exceptions.items() if present}
        if len(reserved) > 1 or (requested_image is not None and reserved - {requested_image}):
            raise ValueError('This keyword is limited to one scan variant. Resolve any duplicates in Keyword review, or remove the current keyword before moving it.')
        wanted = reserved or {active_image}
    changed = False
    failures = []
    for i in images:
        if exceptions.get(i['id'], i['id'] in wanted):
            try:
                changed |= write_one(conn, i['id'], kid, True)
            except Exception as e:
                failures.append(f"{i['path']}: {e}")
    if failures:
        raise ValueError('; '.join(failures))
    return changed


def remove(conn, photo_id, kid, only_app=True):
    inventory(conn)
    conn.execute('DELETE FROM photo_keyword_intents WHERE photo_id=? AND keyword_id=?', (photo_id, kid))
    conn.commit()
    changed = False
    for i in _images(conn, photo_id):
        ex = conn.execute('SELECT present FROM image_keyword_exceptions WHERE image_id=? AND keyword_id=?', (i['id'], kid)).fetchone()
        if only_app and ex and ex[0]:
            continue
        if not only_app:
            exception(conn, i['id'], kid, False)
        if conn.execute('SELECT 1 FROM image_keywords WHERE image_id=? AND keyword_id=?', (i['id'], kid)).fetchone():
            changed |= write_one(conn, i['id'], kid, False, only_app)
    return changed


def set_photo_scope(conn, pid, kid, scope):
    images = _images(conn, pid)
    if not conn.execute('SELECT 1 FROM keywords WHERE id=?', (kid,)).fetchone():
        raise ValueError('No such keyword')
    if not images:
        raise ValueError('No such photograph')
    conn.execute('DELETE FROM photo_keyword_scopes WHERE keyword_id=? AND anchor_image_id IN '
                 '(SELECT id FROM images WHERE photo_id=?)', (kid, pid))
    if scope is not None:
        scope = validate_scope(scope)
        conn.execute('INSERT INTO photo_keyword_scopes VALUES (?,?,?)', (images[0]['id'], kid, json.dumps(scope)))
    conn.commit()


def exception(conn, image_id, kid, present):
    if not conn.execute('SELECT 1 FROM keywords WHERE id=?', (kid,)).fetchone():
        raise ValueError('No such keyword')
    if present is None:
        conn.execute('DELETE FROM image_keyword_exceptions WHERE image_id=? AND keyword_id=?', (image_id, kid))
    else:
        if not conn.execute('SELECT 1 FROM images WHERE id=?', (image_id,)).fetchone():
            raise ValueError('No such image')
        conn.execute('INSERT OR REPLACE INTO image_keyword_exceptions VALUES (?,?,?)', (image_id, kid, int(present)))
    conn.commit()


def review(conn, photo_id=None):
    errors = inventory(conn)
    photos = [photo_id] if photo_id is not None else [r[0] for r in conn.execute('SELECT id FROM photos')]
    differences, exceptions, choices, conflicts = [], [], [], []
    photos_checked = 0
    unreadable = {e['image_id'] for e in errors}
    for pid in photos:
        images = _images(conn, pid)
        if not images:
            continue
        photos_checked += 1
        ids = [i['id'] for i in images]
        marks = ','.join('?' for _ in ids)
        actual = {}
        missing_hierarchy = set()
        for r in conn.execute('SELECT * FROM image_keywords WHERE image_id IN (' + marks + ')', ids):
            actual.setdefault(r['keyword_id'], {})[r['image_id']] = r['source']
            if not r['hierarchical']:
                missing_hierarchy.add((r['image_id'], r['keyword_id']))
        kids = set(actual) | {r[0] for r in conn.execute(
            'SELECT keyword_id FROM photo_keyword_intents WHERE photo_id=?', (pid,))}
        kids |= {r[0] for r in conn.execute('SELECT keyword_id FROM image_keyword_exceptions WHERE image_id IN (' + marks + ')', ids)}
        for kid in sorted(kids):
            scope, inherited = resolve_scope(conn, pid, kid, ids)
            path = keywords.path_of(conn, kid)
            ex = dict(conn.execute('SELECT image_id,present FROM image_keyword_exceptions WHERE keyword_id=? AND image_id IN (' + marks + ')', [kid, *ids]))
            if scope['mode'] == 'ask' and len(ex) < len(images):
                choices.append({'photo_id': pid, 'keyword_id': kid, 'keyword': path, 'path': images[0]['path']})
            present_ids = set(actual.get(kid, {}))
            reserved = present_ids | {image_id for image_id, present in ex.items() if present}
            exclusive_conflict = scope['mode'] == 'one' and len(reserved) > 1
            if exclusive_conflict:
                members = [{'image_id': i['id'], 'path': i['path'], 'variation': i['variation_label'] or i['role'],
                            'present': i['id'] in present_ids, 'exception': bool(ex.get(i['id'])),
                            'source': actual.get(kid, {}).get(i['id'])}
                           for i in images if i['id'] in reserved]
                conflicts.append({'id': f"{pid}:{kid}:" + ','.join(str(i) for i in sorted(reserved)),
                                  'photo_id': pid, 'keyword_id': kid, 'keyword': path, 'variants': members,
                                  'blocked': bool(unreadable.intersection(ids))})
            wanted = targets(images, scope, actual.get(kid, {}))
            for i in images:
                current = i['id'] in actual.get(kid, {})
                expected = bool(ex.get(i['id'], i['id'] in wanted))
                item = {'photo_id': pid, 'image_id': i['id'], 'keyword_id': kid, 'keyword': path,
                        'path': i['path'], 'variation': i['variation_label'] or i['role'],
                        'source': actual.get(kid, {}).get(i['id']),
                        'inherited': 'Individual-file exception' if i['id'] in ex else inherited,
                        'present': current, 'expected': expected}
                if i['id'] in ex:
                    exceptions.append(item)
                needs_hierarchy = expected and (i['id'], kid) in missing_hierarchy and i['id'] not in ex and scope['mode'] != 'ask'
                if not exclusive_conflict and (current != expected or needs_hierarchy) and i['id'] not in unreadable:
                    differences.append({**item, 'action': 'add' if expected else 'remove',
                                        'id': f"{i['id']}:{kid}:{'add' if expected else 'remove'}",
                                        'reason': 'Missing hierarchy' if needs_hierarchy else ('Missing keyword' if expected else 'Outside selected scope')})
    from . import variations
    cfg = variations.load(conn)
    grouping_issues = []
    if cfg['enabled']:
        overrides = {r[0] for r in conn.execute('SELECT image_id FROM image_group_overrides')}
        for image in conn.execute('SELECT id,path FROM images'):
            item = variations.classify(image['path'], cfg)
            if item['issue'] and image['id'] not in overrides:
                grouping_issues.append({'image_id': image['id'], 'path': image['path'],
                                        'suffix': item['suffix'], 'issue': item['issue']})
    return {'photos_checked': photos_checked, 'differences': differences, 'exceptions': exceptions, 'choices': choices,
            'errors': errors, 'grouping_issues': grouping_issues, 'conflicts': conflicts}


def apply_review(conn, selections):
    # Recompute instead of trusting stale client paths, sources or action types.
    pending = {r['id']: r for r in review(conn)['differences']}
    completed, errors = [], []
    for selection in selections:
        r = pending.get(selection['id'])
        if not r:
            errors.append({'id': selection['id'], 'error': 'This difference changed; review it again'})
            continue
        if r['source'] == 'file' and r['action'] == 'remove' and not selection.get('allow_owner_removal'):
            errors.append({'id': r['id'], 'error': 'Explicitly confirm removal of an existing owner keyword'})
            continue
        try:
            if not write_one(conn, r['image_id'], r['keyword_id'], r['expected'], only_app=r['source'] != 'file'):
                raise ValueError('The keyword now belongs to the owner; check it again before removing')
            completed.append(r['id'])
        except Exception as e:
            errors.append({'id': r['id'], 'error': str(e)})
    return {'completed': completed, 'errors': errors, 'review': review(conn)}


def resolve_exclusive(conn, conflict_id, keep_image_id):
    conflict = next((row for row in review(conn)['conflicts'] if row['id'] == conflict_id), None)
    if not conflict or conflict['blocked']:
        raise ValueError('This conflict changed or a scan variant cannot be read. Check again before applying.')
    keeper = next((v for v in conflict['variants'] if v['image_id'] == keep_image_id), None)
    if not keeper:
        raise ValueError('Choose a scan variant listed in this conflict')
    kid = conflict['keyword_id']
    # This is an explicit user choice; do not remove anything until the keeper is in place.
    if not keeper['present']:
        write_one(conn, keep_image_id, kid, True)
    if not keeper['exception']:
        exception(conn, keep_image_id, kid, None)
    for variant in conflict['variants']:
        image_id = variant['image_id']
        if image_id == keep_image_id:
            continue
        if variant['present']:
            write_one(conn, image_id, kid, False, only_app=False)
        if variant['exception']:
            exception(conn, image_id, kid, None)


def difference_count(result):
    return len(result['differences']) + len(result['conflicts'])


def update_pending(conn):
    result = review(conn)
    count = difference_count(result) + len(result['choices']) + len(result['errors']) + len(result['grouping_issues'])
    db.set_setting(conn, 'sharing.pending', str(count))
    conn.commit()
    return result
