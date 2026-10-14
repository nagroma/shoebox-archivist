"""Command-line interface for the Phase 1 recognition spike.

    uv run pm ingest "D:/Family Photos"     # register images + detect faces
    uv run pm review                         # cluster, suggest, write data/report.html
    uv run pm label --cluster 3 --name "Ruth Smith" --exclude 41,57
    uv run pm evaluate                       # leave-one-out accuracy, b&w vs colour
    uv run pm serve                          # web UI at http://127.0.0.1:8765
    uv run pm baseline save photos           # snapshot originals; 'restore' resets for testing
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from . import actions, baseline, cluster, config, dates, db, ingest, library, match, xmp

DATA = Path(os.environ.get("PM_DATA", Path(__file__).resolve().parent.parent / "data"))


def _ids(text: str | None) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()] if text else []


def _target_faces(conn: sqlite3.Connection, args) -> list[int]:
    if args.cluster is not None:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM faces WHERE cluster_id = ? AND status IN ('unknown', 'suggested')",
            (args.cluster,))]
    else:
        ids = _ids(args.faces)
    excluded = set(_ids(getattr(args, "exclude", None)))
    return [i for i in ids if i not in excluded]


def refresh(conn: sqlite3.Connection, args) -> None:
    n_sugg = match.suggest(conn, args.threshold)
    n_clusters = cluster.cluster(conn, args.min_size)
    out = DATA / "report.html"
    cluster.report(conn, out, DATA / "thumbs")
    print(f"{n_sugg} suggestions, {n_clusters} clusters -> {out}")


def cmd_ingest(conn, args):
    if args.rescan or args.rescan_empty:
        only_empty = "" if args.rescan else "AND id NOT IN (SELECT image_id FROM faces)"
        n = conn.execute("UPDATE images SET faces_scanned = 0 WHERE role = 'front' "
                         f"AND faces_scanned = 1 {only_empty}").rowcount
        conn.commit()
        print(f"Re-scanning {n} photo(s); existing faces and names are kept")
    try:
        ingest.ingest(conn, Path(args.folder), DATA / "thumbs", args.det_size,
                      thorough=False if args.fast else None)
    except ValueError as e:
        raise SystemExit(str(e))
    refresh(conn, args)


def cmd_review(conn, args):
    refresh(conn, args)


def cmd_label(conn, args):
    ids = _target_faces(conn, args)
    if not ids:
        raise SystemExit("No matching faces.")
    actions.assign(conn, ids, db.get_or_create_person(conn, args.name))
    print(f"Labeled {len(ids)} faces as {args.name}")
    refresh(conn, args)


def cmd_reject(conn, args):
    """Reject the current name on these faces (stores a negative example)."""
    print(f"Rejected {actions.reject(conn, _target_faces(conn, args))} names")
    refresh(conn, args)


def cmd_ignore(conn, args):
    """Mark faces as not worth naming (strangers, paintings, false detections)."""
    ids = _target_faces(conn, args)
    actions.ignore(conn, ids)
    print(f"Ignored {len(ids)} faces")
    refresh(conn, args)


def cmd_unlabel(conn, args):
    actions.reject(conn, _ids(args.faces))
    refresh(conn, args)


def cmd_person(conn, args):
    pid = db.get_or_create_person(conn, args.name)
    if args.born is not None:
        conn.execute("UPDATE people SET birth_year = ? WHERE id = ?", (args.born, pid))
    if args.died is not None:
        conn.execute("UPDATE people SET death_year = ? WHERE id = ?", (args.died, pid))
    conn.commit()


def cmd_date(conn, args):
    fd = dates.parse(args.text)
    if fd is None:
        raise SystemExit(f"Can't understand date: {args.text!r}")
    row = conn.execute("SELECT photo_id FROM images WHERE path = ? OR id = ?",
                       (args.image, args.image)).fetchone()
    if row is None:
        raise SystemExit(f"No image {args.image!r}")
    conn.execute("UPDATE photos SET date_text = ?, date_min = ?, date_max = ?, precision = ? "
                 "WHERE id = ?", (fd.edtf, fd.date_min.isoformat(), fd.date_max.isoformat(),
                                  fd.precision, row["photo_id"]))
    conn.commit()
    print(f"{fd}  [{fd.edtf}, {fd.date_min} .. {fd.date_max}]")


def cmd_evaluate(conn, args):
    match.evaluate(conn, args.threshold if args.threshold is not None
                   else config.get(conn, "suggest_threshold"))


def _wipe_data() -> None:
    import shutil
    for name in ("library.db", "library.db-wal", "library.db-shm", "report.html"):
        (DATA / name).unlink(missing_ok=True)
    for name in ("thumbs", "cache"):
        shutil.rmtree(DATA / name, ignore_errors=True)


def cmd_baseline(conn, args):
    dest = DATA / "baseline"
    if args.action == "save":
        root = Path(args.folder).resolve() if args.folder else db.library_root(conn)
        print(f"Saved {baseline.save(root, dest)} files from {root} to {dest}")
        return
    if not (dest / baseline.MANIFEST).exists():
        raise SystemExit("No baseline yet - run 'pm baseline save <folder>' first.")
    import json
    root = Path(json.loads((dest / baseline.MANIFEST).read_text())["root"])
    restored, unchanged, extra = baseline.restore(root, dest)
    print(f"Restored {restored} changed files ({unchanged} unchanged) in {root}")
    for rel in extra:
        print(f"  not in baseline (left alone): {rel}")
    if not args.keep_db:
        conn.close()
        _wipe_data()
        print(f"Deleted the database, face thumbnails and cache in {DATA}")


def cmd_regroup(conn, args):
    """Convert family-name groups (Ashdown|JuliaAshdown) into People|JuliaAshdown + Family|Ashdown."""
    from . import regroup
    p = regroup.plan(conn, args.groups, args.people)
    for g in p["groups"]:
        print(f"{g['group']}: {len(g['people'])} keywords -> {p['people_category']}|<name> + {g['family_keyword']}")
        for x in g["people"]:
            print(f"  {x['name']:<24} {x['photos']:>4} photos{'  (People keyword exists: merged)' if x['merges_existing'] else ''}")
        if g["skipped_deeper"]:
            print(f"  {g['skipped_deeper']} deeper keywords under {g['group']} are left alone")
    print(f"{p['photos']} photos would change.")
    if not args.apply:
        print("Nothing changed. Re-run with --apply to do it.")
        return
    r = regroup.apply(conn, args.groups, args.people)
    print(f"Converted {r['converted']} keywords on photos ({r['failed']} failed). `pm strip` undoes it.")


def cmd_strip(conn, args):
    """Remove every keyword this app wrote to the files (sa:AddedKeywords)."""
    root = db.library_root(conn)
    n_files = n_kw = 0
    for r in conn.execute("SELECT path FROM images").fetchall():
        gone = xmp.strip_app_keywords(root / r["path"])
        fields = xmp.restore_fields(root / r["path"])
        if gone or fields:
            n_files += 1
            n_kw += len(gone)
    conn.execute("DELETE FROM photo_keywords WHERE source = 'app'")
    conn.commit()
    print(f"Removed {n_kw} app-added keywords and restored edited caption/date/location "
          f"in {n_files} files. Re-ingest into a fresh DB to match the files.")


def cmd_serve(conn, args):
    import webbrowser
    import uvicorn
    from . import api
    if args.explicit_data:
        library.use_data_dir(args.db.parent)
    else:  # the last library used, else an older ./data folder, else the setup page
        library.open_startup(DATA)
    shown = library.data_dir()
    print(f"Library data: {shown if shown else 'none yet - choose a folder in the web UI'}")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Shoebox Archivist running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def cmd_status(conn, args):
    q = lambda sql: conn.execute(sql).fetchone()[0]
    print(f"library root : {db.get_setting(conn, 'library_root')}")
    print(f"photos       : {q('SELECT COUNT(*) FROM photos')}")
    fronts = q("SELECT COUNT(*) FROM images WHERE role = 'front'")
    backs = q("SELECT COUNT(*) FROM images WHERE role = 'back'")
    bw = q("SELECT COUNT(*) FROM images WHERE is_bw = 1")
    print(f"images       : {fronts} fronts, {backs} backs, {bw} b&w")
    for status, n in conn.execute("SELECT status, COUNT(*) FROM faces GROUP BY status"):
        print(f"faces        : {n} {status}")
    print(f"people       : {q('SELECT COUNT(*) FROM people')}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pm", description="Family photo manager - prototype CLI")
    p.add_argument("--db", type=Path, default=None,
                   help="database file (default: PM_DATA or ./data; 'serve' opens the last library)")
    p.add_argument("--library", type=Path, default=None,
                   help="photo folder whose .shoebox data folder to use")
    p.add_argument("--threshold", type=float, default=None,
                   help="cosine similarity needed to suggest a name (default: from Settings)")
    p.add_argument("--min-size", type=int, default=None,
                   help="minimum faces per cluster (default: from Settings)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="register images in a folder and detect faces")
    s.add_argument("folder")
    s.add_argument("--det-size", type=int, default=1024)
    s.add_argument("--rescan-empty", action="store_true",
                   help="look again for faces in photos where none were found")
    s.add_argument("--rescan", action="store_true",
                   help="look again for missed faces in every photo (keeps existing faces/names)")
    s.add_argument("--fast", action="store_true",
                   help="fast detection for this run (default: the mode in Settings)")
    s.set_defaults(func=cmd_ingest)

    sub.add_parser("review", help="re-cluster, suggest, and rebuild the HTML report"
                   ).set_defaults(func=cmd_review)

    for name, func, hlp in [("label", cmd_label, "name faces"),
                            ("reject", cmd_reject, "reject suggestions"),
                            ("ignore", cmd_ignore, "ignore faces")]:
        s = sub.add_parser(name, help=hlp)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--cluster", type=int)
        g.add_argument("--faces", help="comma-separated face ids")
        s.add_argument("--exclude", help="face ids to leave out")
        if name == "label":
            s.add_argument("--name", required=True)
        s.set_defaults(func=func)

    s = sub.add_parser("unlabel", help="reset faces to unknown")
    s.add_argument("--faces", required=True)
    s.set_defaults(func=cmd_unlabel)

    s = sub.add_parser("person", help="set birth/death years (filters impossible suggestions)")
    s.add_argument("--name", required=True)
    s.add_argument("--born", type=int)
    s.add_argument("--died", type=int)
    s.set_defaults(func=cmd_person)

    s = sub.add_parser("date", help="set a fuzzy date on a photo, e.g. 'c. 1925'")
    s.add_argument("image", help="image id or path relative to library root")
    s.add_argument("text")
    s.set_defaults(func=cmd_date)

    sub.add_parser("evaluate", help="leave-one-out accuracy on confirmed faces"
                   ).set_defaults(func=cmd_evaluate)
    sub.add_parser("status").set_defaults(func=cmd_status)

    s = sub.add_parser("baseline", help="save / restore a known state of the photos (testing)")
    s.add_argument("action", choices=["save", "restore"])
    s.add_argument("folder", nargs="?", help="library folder (save only; default: library root)")
    s.add_argument("--keep-db", action="store_true", help="restore files but keep the database")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("regroup", help="turn family-name groups (Ashdown|JuliaAshdown) into "
                       "People|JuliaAshdown + Family|Ashdown (preview unless --apply)")
    s.add_argument("groups", nargs="+", help="top-level groups, e.g. Ashdown Marlowe AshdownMarlowe")
    s.add_argument("--people", help="person group to use (default: the library's person facet)")
    s.add_argument("--apply", action="store_true", help="write the change (default: preview only)")
    s.set_defaults(func=cmd_regroup)

    sub.add_parser("strip", help="undo everything this app wrote to the photo files"
                   ).set_defaults(func=cmd_strip)

    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    global DATA
    if args.library:
        DATA = library.data_dir_for(args.library.resolve())
    args.explicit_data = bool(args.library or args.db or os.environ.get("PM_DATA"))
    if args.db is None:
        args.db = DATA / "library.db"
    if args.cmd == "serve" and not args.explicit_data:
        args.func(None, args)  # may start without any library
        return
    conn = db.connect(args.db)
    try:
        args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
