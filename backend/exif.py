"""Read date taken + GPS from image EXIF, and turn GPS into a place name offline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 36867   # when the shutter fired - NOT DateTime/Digitized (= scan/edit time)
MAKE, MODEL = 271, 272

# Scanner EXIF "date taken" is the scan date, not when the photo was taken.
SCANNER_HINTS = ("scan", "epson perfection", "canoscan", "fastfoto", "flatbed", "photosmart")


@dataclass
class ExifInfo:
    taken: datetime | None = None
    lat: float | None = None
    lon: float | None = None
    camera: str | None = None


def _dms(value, ref: str | None) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def read(path: Path) -> ExifInfo:
    info = ExifInfo()
    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:
        return info
    make = str(exif.get(MAKE, "") or "").strip("\x00 ")
    model = str(exif.get(MODEL, "") or "").strip("\x00 ")
    info.camera = " ".join(x for x in (make, model) if x) or None
    is_scanner = any(h in (info.camera or "").lower() for h in SCANNER_HINTS)

    raw = exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL)
    if raw and not is_scanner:
        try:
            dt = datetime.strptime(str(raw).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
            if dt.year >= 1826:  # rejects zeroed/garbage values
                info.taken = dt
        except ValueError:
            pass

    gps = exif.get_ifd(GPS_IFD)
    if gps:
        lat, lon = _dms(gps.get(2), gps.get(1)), _dms(gps.get(4), gps.get(3))
        if lat is not None and lon is not None and not (lat == 0 and lon == 0):
            info.lat, info.lon = round(lat, 6), round(lon, 6)
    return info


@lru_cache(maxsize=1)
def _geocoder():
    import reverse_geocoder
    return reverse_geocoder.RGeocoder(mode=1, verbose=False)


def place_name(lat: float, lon: float) -> str | None:
    """Nearest town (GeoNames, population > 1000), e.g. 'Lancaster, Pennsylvania, US'.
    Approximate: rural photos get the nearest town."""
    try:
        r = _geocoder().query([(lat, lon)])[0]
    except Exception:
        return None
    parts = [r.get("name"), r.get("admin1"), r.get("cc")]
    return ", ".join(p for p in parts if p) or None
