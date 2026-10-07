"""Citizen photo sanitising (LLD APAC 9.2).

Sniff the bytes (the declared content type is not trusted), enforce the size
and pixel limits before and during decode, read the EXIF facts the geo check
needs, then re-encode from pixels so no metadata survives. The SHA-256 is of
the sanitized bytes, which is what is stored and deduplicated.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

#: EXIF tag and IFD ids (EXIF 2.32 / TIFF 6.0).
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4
_GPS_IMG_DIRECTION = 17

_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("image/jpeg", "JPEG"),
    ("image/png", "PNG"),
    ("image/webp", "WEBP"),
)


class RejectedImageError(ValueError):
    """The upload is not an acceptable still image. ``reason`` is stable for logs."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExifFacts:
    lat: float | None = None
    lon: float | None = None
    #: Capture time when EXIF also recorded its UTC offset.
    taken_at: datetime | None = None
    #: Capture time without an offset: the phone's wall clock, zone unknown.
    taken_at_local: datetime | None = None
    #: Degrees clockwise from north the camera pointed, when the phone recorded it.
    img_direction_deg: float | None = None

    @property
    def has_gps(self) -> bool:
        return self.lat is not None and self.lon is not None

    def capture_time(self, timezone: tzinfo) -> datetime | None:
        """Capture time in UTC, reading an offset-less wall clock in ``timezone``."""
        if self.taken_at is not None:
            return self.taken_at
        if self.taken_at_local is not None:
            return self.taken_at_local.replace(tzinfo=timezone).astimezone(UTC)
        return None


@dataclass(frozen=True)
class SanitizedImage:
    data: bytes
    content_type: str
    sha256: str
    width: int
    height: int
    exif: ExifFacts


def sniff(data: bytes) -> str | None:
    """Content type from magic bytes, or ``None``."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize(
    data: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
    allowed_mime: tuple[str, ...],
) -> SanitizedImage:
    """Validate, read EXIF, strip it by re-encoding, and hash the result.

    Raises:
        RejectedImageError: empty, too large, not an allowed type, undecodable,
            or above the pixel limit.
    """
    if not data:
        raise RejectedImageError("empty_upload")
    if len(data) > max_bytes:
        raise RejectedImageError("too_large")
    mime = sniff(data)
    if mime is None or mime not in allowed_mime:
        raise RejectedImageError("unsupported_type")
    expected_format = dict(_SIGNATURES)[mime]

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != expected_format:
                    raise RejectedImageError("unsupported_type")
                if probe.width * probe.height > max_pixels:
                    raise RejectedImageError("too_many_pixels")
                if getattr(probe, "n_frames", 1) > 1:
                    raise RejectedImageError("animated_image")
                facts = _exif_facts(probe.getexif())
                probe.load()
                upright = ImageOps.exif_transpose(probe)
                pixels = upright.convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise RejectedImageError("too_many_pixels") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise RejectedImageError("undecodable") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    out = io.BytesIO()
    pixels.save(out, format="JPEG", quality=90, optimize=True)
    clean = out.getvalue()
    return SanitizedImage(
        data=clean,
        content_type="image/jpeg",
        sha256=hashlib.sha256(clean).hexdigest(),
        width=pixels.width,
        height=pixels.height,
        exif=facts,
    )


def has_metadata(data: bytes) -> bool:
    """Whether an image still carries EXIF (used to prove sanitising worked)."""
    with Image.open(io.BytesIO(data)) as image:
        return bool(image.getexif()) or "exif" in image.info


def _exif_facts(exif: Image.Exif) -> ExifFacts:
    gps = _ifd(exif, _GPS_IFD)
    details = _ifd(exif, _EXIF_IFD)
    lat = _coordinate(gps.get(_GPS_LAT), gps.get(_GPS_LAT_REF), "S")
    lon = _coordinate(gps.get(_GPS_LON), gps.get(_GPS_LON_REF), "W")
    direction = _number(gps.get(_GPS_IMG_DIRECTION))
    if direction is not None and not 0.0 <= direction <= 360.0:
        direction = None
    taken_at, taken_at_local = _timestamp(
        details.get(_DATETIME_ORIGINAL), details.get(_OFFSET_TIME_ORIGINAL)
    )
    if lat is not None and not -90.0 <= lat <= 90.0:
        lat = None
    if lon is not None and not -180.0 <= lon <= 180.0:
        lon = None
    return ExifFacts(
        lat=lat if lon is not None else None,
        lon=lon if lat is not None else None,
        taken_at=taken_at,
        taken_at_local=taken_at_local,
        img_direction_deg=direction % 360.0 if direction is not None else None,
    )


def _ifd(exif: Image.Exif, tag: int) -> dict[int, Any]:
    try:
        return dict(exif.get_ifd(tag))
    except (KeyError, ValueError, TypeError):
        return {}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if number == number else None


def _coordinate(value: Any, ref: Any, negative: str) -> float | None:
    if not isinstance(value, tuple | list) or len(value) != 3:
        return None
    parts = [_number(v) for v in value]
    if any(p is None for p in parts):
        return None
    degrees, minutes, seconds = (p for p in parts if p is not None)
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    text = ref.decode() if isinstance(ref, bytes) else str(ref or "")
    return -decimal if text.strip().upper() == negative else decimal


def _timestamp(value: Any, offset: Any) -> tuple[datetime | None, datetime | None]:
    """``(aware UTC time, naive local time)``: exactly one is set when EXIF has a time."""
    if not isinstance(value, str):
        return None, None
    try:
        naive = datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None
    text = offset.strip() if isinstance(offset, str) else ""
    try:
        aware = datetime.fromisoformat(f"{naive.isoformat()}{text}") if text else None
    except ValueError:
        aware = None
    if aware is None:
        return None, naive
    return aware.astimezone(UTC), None
