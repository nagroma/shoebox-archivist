"""Read and write the keyword metadata embedded in photo files (XMP).

The photos carry Lightroom/Bridge-style keywords:
  lr:hierarchicalSubject  ['Smith|JohnSmith', 'Attributes|unknowndate']     <- source of truth
  dc:subject              ['JohnSmith', 'unknowndate']                     <- flat copy
plus photoshop:DateCreated and dc:description (caption).
Bridge also keeps legacy copies (IPTC Keywords/Caption/DateCreated, EXIF ImageDescription/
DateTimeOriginal). When the app changes a value it updates those copies too, so other
apps don't show stale data - IPTC only if the file has an IPTC record, EXIF only for tags
already present.

Every keyword this app adds is also listed in its own namespace (sa:AddedKeywords),
so app changes can be told apart from the owner's and stripped again (`pm strip`).
An owner keyword the app removes (a regroup) is listed in sa:RemovedKeywords and restored by strip.
Edited fields (caption, date, location) keep their pre-app value in sa:Original*.

Fuzzy dates: photoshop:DateCreated gets the most precise plain date XMP allows
('1975', '1975-05', '1975-05-01'); the full EDTF ('1975~', '1920/1925') goes in sa:DateEDTF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pyexiv2

# The namespace URI is kept from the original project name (the prefix is only a label): it is
# already written into photos, and changing it would orphan existing provenance (strip could not undo it).
PM_NS = "http://photo-manager.local/ns/1.0/"
HS, SUBJ, ADDED = "Xmp.lr.hierarchicalSubject", "Xmp.dc.subject", "Xmp.sa.AddedKeywords"
# Owner keywords the app removed on purpose (a regroup); `pm strip` puts them back.
REMOVED = "Xmp.sa.RemovedKeywords"
DESC, DATE, EDTF, LOC = ("Xmp.dc.description", "Xmp.photoshop.DateCreated", "Xmp.sa.DateEDTF",
                         "Xmp.iptc.Location")  # Iptc4xmpCore:Location
# field -> where its value from before the app's first edit is kept
IPTC_KW, IPTC_CAPTION, IPTC_DATE, IPTC_SUBLOC = (
    "Iptc.Application2.Keywords", "Iptc.Application2.Caption", "Iptc.Application2.DateCreated",
    "Iptc.Application2.SubLocation")
EXIF_DESC, EXIF_DTO, EXIF_XPKW = ("Exif.Image.ImageDescription", "Exif.Photo.DateTimeOriginal",
                                  "Exif.Image.XPKeywords")
ORIGINALS = {DESC: "Xmp.sa.OriginalDescription", DATE: "Xmp.sa.OriginalDateCreated",
             LOC: "Xmp.sa.OriginalLocation",
             IPTC_CAPTION: "Xmp.sa.OriginalIptcCaption", IPTC_DATE: "Xmp.sa.OriginalIptcDateCreated",
             IPTC_SUBLOC: "Xmp.sa.OriginalIptcSubLocation",
             EXIF_DESC: "Xmp.sa.OriginalExifImageDescription",
             EXIF_DTO: "Xmp.sa.OriginalExifDateTimeOriginal"}
UNSET = "(none)"
KEYWORD_KEYS = (HS, SUBJ, IPTC_KW)
MANAGED = (*KEYWORD_KEYS, *ORIGINALS)  # every tag this app may write (besides its own sa:*)  # marks "the field was empty before the app set it"

# Register namespaces before writing, or exiv2 renames unknown prefixes (ff -> prefix0_1_).
for _uri, _prefix in [(PM_NS, "sa"), ("http://fastfoto.com/1.0/", "ff"),
                      ("http://ns.adobe.com/bridge/1.0/", "kbrg")]:
    try:
        pyexiv2.registerNs(_uri, _prefix)
    except Exception:  # already registered
        pass


@dataclass
class XmpInfo:
    keywords: list[str] = field(default_factory=list)   # 'Category|Name'
    flat: list[str] = field(default_factory=list)       # dc:subject
    app_added: list[str] = field(default_factory=list)  # subset of keywords added by us
    removed: list[str] = field(default_factory=list)    # owner keywords we removed (sa:RemovedKeywords)
    date_created: str | None = None
    date_edtf: str | None = None        # set by this app
    description: str | None = None
    location: str | None = None
    other: list[str] = field(default_factory=list)      # IPTC Keywords + Windows XPKeywords


def _list(v) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def _lang_alt(v) -> str | None:
    if isinstance(v, dict):
        v = v.get('lang="x-default"') or next(iter(v.values()), None)
    return (v or "").strip() or None


def _xp(v) -> list[str]:
    """Windows XPKeywords: UCS-2, ';'-separated (exiv2 may hand it over as byte numbers)."""
    if not v:
        return []
    if isinstance(v, str) and all(t.isdigit() for t in v.split()):
        v = bytes(int(t) for t in v.split()).decode("utf-16-le", "ignore")
    return [k.strip() for k in str(v).strip("\x00").split(";") if k.strip()]


def read(path: Path) -> XmpInfo:
    try:
        with pyexiv2.Image(str(path)) as im:
            x = im.read_xmp()
            other = _list(im.read_iptc().get(IPTC_KW)) + _xp(im.read_exif().get(EXIF_XPKW))
    except Exception:
        return XmpInfo()
    return XmpInfo(
        keywords=_list(x.get(HS)),
        flat=_list(x.get(SUBJ)),
        app_added=_list(x.get(ADDED)),
        removed=_list(x.get(REMOVED)),
        date_created=x.get(DATE) or None,
        date_edtf=x.get(EDTF) or None,
        description=_lang_alt(x.get(DESC)),
        location=x.get(LOC) or None,
        other=list(dict.fromkeys(other)),
    )


def read_all(path: Path) -> dict[str, dict]:
    """Every EXIF / IPTC / XMP tag in the file, for display."""
    with pyexiv2.Image(str(path)) as im:
        return {"exif": im.read_exif(), "iptc": im.read_iptc(), "xmp": im.read_xmp()}


def read_all_safe(path: Path) -> tuple[dict[str, dict], str | None]:
    """read_all, but a file exiv2 can't open (e.g. a damaged maker-note preview) still shows
    the EXIF that Pillow can read. Returns (tags, warning)."""
    try:
        return read_all(path), None
    except Exception as e:
        warning = (f"This file's metadata block is damaged ({str(e).splitlines()[0]}). "
                   "The app can't read its keywords or write to it; the image itself is fine.")
    exif: dict = {}
    try:
        from PIL import ExifTags, Image
        with Image.open(path) as im:
            for tag, val in im.getexif().items():
                if isinstance(val, bytes):
                    continue
                exif[f"Exif.Image.{ExifTags.TAGS.get(tag, hex(tag))}"] = str(val)
    except Exception:
        pass
    return {"exif": exif, "iptc": {}, "xmp": {}}, warning


def _full_date(d: str) -> str:
    """'1975' / '1975-05' / '1975-05-01T..' -> '1975-01-01' etc. (IPTC/EXIF need a full date)."""
    parts = d[:10].split("-") + ["01", "01"]
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def _apply(im, out: dict) -> None:
    for group, fn in (("Xmp", im.modify_xmp), ("Iptc", im.modify_iptc), ("Exif", im.modify_exif)):
        if out[group]:
            fn(out[group])


def write_fields(path: Path, *, description: str | None | bool = False,
                 date_created: str | None | bool = False, date_edtf: str | None = None,
                 location: str | None | bool = False) -> None:
    """Write caption / date / location into the file (False = leave alone, None = clear).
    The first time the app changes a field its previous value is saved in sa:Original*."""
    with pyexiv2.Image(str(path)) as im:
        cur = {"Xmp": im.read_xmp(), "Iptc": im.read_iptc(), "Exif": im.read_exif()}
        out: dict = {"Xmp": {}, "Iptc": {}, "Exif": {}}
        x = cur["Xmp"]

        def put(key: str, value) -> None:
            group = key.split(".", 1)[0]
            have = cur[group]
            if (group == "Iptc" and not have) or (group == "Exif" and key not in have):
                return  # don't create legacy fields the file never had
            orig = ORIGINALS[key]
            if orig not in x:
                before = _lang_alt(have.get(key)) if key == DESC else have.get(key)
                out["Xmp"][orig] = before or UNSET
            out[group][key] = value

        if description is not False:
            put(DESC, {'lang="x-default"': description} if description else None)
            put(IPTC_CAPTION, description or None)
            put(EXIF_DESC, description or None)
        if date_created is not False:
            put(DATE, date_created or None)
            out["Xmp"][EDTF] = date_edtf if date_created else None
            put(IPTC_DATE, _full_date(date_created) if date_created else None)
            put(EXIF_DTO, _full_date(date_created).replace("-", ":") + " 00:00:00"
                if date_created else None)
        if location is not False:
            put(LOC, location or None)
            put(IPTC_SUBLOC, location or None)
        _apply(im, out)


def restore_fields(path: Path) -> list[str]:
    """Put back the values fields had before this app edited them."""
    with pyexiv2.Image(str(path)) as im:
        x = im.read_xmp()
        out: dict = {"Xmp": {}, "Iptc": {}, "Exif": {}}
        for key, orig in ORIGINALS.items():
            if orig in x:
                v = x[orig]
                out[key.split(".", 1)[0]][key] = \
                    None if v == UNSET else ({'lang="x-default"': v} if key == DESC else v)
                out["Xmp"][orig] = None
        if EDTF in x:
            out["Xmp"][EDTF] = None
        _apply(im, out)
    return [k for k in (DESC, DATE, LOC) if k in out["Xmp"]]


def leaf(keyword: str) -> str:
    return keyword.rsplit("|", 1)[-1]


def _write(path: Path, hs: list[str], flat: list[str], added: list[str],
           iptc_add: list[str] = (), iptc_remove: set[str] = frozenset(),
           removed: list[str] | None = None) -> None:
    with pyexiv2.Image(str(path)) as im:
        fields = {HS: hs or None, SUBJ: flat or None, ADDED: added or None}
        if removed is not None:
            fields[REMOVED] = removed or None
        im.modify_xmp(fields)
        iptc = im.read_iptc()
        if iptc:  # keep Bridge's IPTC copy in step
            kws = [k for k in _list(iptc.get(IPTC_KW)) if k not in iptc_remove]
            kws += [k for k in iptc_add if k not in kws]
            im.modify_iptc({IPTC_KW: kws or None})


def add_keywords(path: Path, keywords: list[str]) -> list[str]:
    """Add hierarchical keywords (and their leaf to dc:subject). Returns those actually added."""
    info = read(path)
    new = [k for k in keywords if k not in info.keywords]
    if not new:
        return []
    flat = info.flat + [leaf(k) for k in new if leaf(k) not in info.flat]
    _write(path, info.keywords + new, flat, info.app_added + new, iptc_add=[leaf(k) for k in new])
    return new


def remove_keywords(path: Path, keywords: list[str], only_app_added: bool = True) -> list[str]:
    """Remove keywords. By default only ones this app added - never the owner's own."""
    info = read(path)
    gone = [k for k in keywords if k in info.keywords
            and (not only_app_added or k in info.app_added)]
    if not gone:
        return []
    hs = [k for k in info.keywords if k not in gone]
    still = {leaf(k) for k in hs}
    flat = [f for f in info.flat if f in still or f not in {leaf(k) for k in gone}]
    owner = [k for k in gone if k not in info.app_added]   # owner's own: remember to restore
    removed = info.removed + [k for k in owner if k not in info.removed] if owner else None
    _write(path, hs, flat, [k for k in info.app_added if k not in gone],
           iptc_remove={leaf(k) for k in gone} - still, removed=removed)
    return gone


def strip_app_keywords(path: Path) -> list[str]:
    """Undo everything this app wrote to the file's keywords, and put back owner keywords it removed."""
    info = read(path)
    gone = remove_keywords(path, info.app_added)
    back = [k for k in info.removed if k not in read(path).keywords]
    if info.removed:
        cur = read(path)
        flat = cur.flat + [leaf(k) for k in back if leaf(k) not in cur.flat]
        _write(path, cur.keywords + back, flat, cur.app_added,
               iptc_add=[leaf(k) for k in back], removed=[])
    return gone
