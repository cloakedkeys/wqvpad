"""Turning watch data into ordinary image files.

* WQV-1 / WQV-2: each photo is a fixed 7229-byte record (name, timestamp,
  120x120 pixels at 4 bits each). Saved as greyscale PNG.
* WQV-3 / WQV-10: each photo is already a JPEG, with Casio's title and
  timestamp in a private APP2 segment. That segment is swapped for standard
  EXIF so photo apps show the date and title.

No third-party imaging library is needed.
"""

from __future__ import annotations

import datetime as dt
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------- WQV-1 / WQV-2
W = H = 120
MONO_RECORD = 24 + 5 + W * H // 2  # 7229 (0x1C3D)


@dataclass
class MonoPhoto:
    title: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    pixels: bytes  # W*H bytes, 0 = black .. 255 = white

    @property
    def timestamp(self) -> Optional[dt.datetime]:
        try:
            return dt.datetime(self.year, self.month, self.day, self.hour, self.minute)
        except ValueError:
            return None


def parse_mono_record(rec: bytes) -> MonoPhoto:
    if len(rec) != MONO_RECORD:
        raise ValueError(f"WQV-1/2 photo record must be {MONO_RECORD} bytes, got {len(rec)}")
    title = rec[:24].decode("latin-1").rstrip(" \x00")
    year2k, month, day, hour, minute = rec[24:29]
    packed = rec[29:]
    px = bytearray(W * H)
    for i in range(W * H):
        b = packed[i // 2]
        nib = (b & 0x0F) if i % 2 == 0 else (b >> 4)  # low nibble first
        px[i] = 255 - nib * 17  # 0 means white on the watch
    return MonoPhoto(title, 2000 + year2k, month, day, hour, minute, bytes(px))


def split_mono_dump(dump: bytes) -> list[MonoPhoto]:
    n = len(dump) // MONO_RECORD
    return [parse_mono_record(dump[i * MONO_RECORD:(i + 1) * MONO_RECORD]) for i in range(n)]


def png_grey(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------- WQV-3 / WQV-10
@dataclass
class JpegMeta:
    title: str = ""
    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0

    @property
    def timestamp(self) -> Optional[dt.datetime]:
        try:
            return dt.datetime(self.year, self.month, self.day, self.hour, self.minute)
        except ValueError:
            return None


def _exif_blob(meta: JpegMeta, model: int) -> bytes:
    """Minimal EXIF APP1 segment (little-endian TIFF, IFD0 only)."""
    tags: list[tuple[int, bytes]] = []
    if meta.title:
        tags.append((0x010E, meta.title.encode("latin-1", "replace") + b"\x00"))  # ImageDescription
    tags.append((0x010F, b"Casio\x00"))                                           # Make
    tags.append((0x0110, f"WQV-{model}".encode() + b"\x00"))                       # Model
    ts = meta.timestamp
    if ts:
        tags.append((0x0132, ts.strftime("%Y:%m:%d %H:%M:%S").encode() + b"\x00"))  # DateTime
    tags.sort()
    n = len(tags)
    ifd_size = 2 + n * 12 + 4
    data_off = 8 + ifd_size
    entries = b""
    extra = b""
    for tag, val in tags:
        if len(val) <= 4:
            entries += struct.pack("<HHI", tag, 2, len(val)) + val.ljust(4, b"\x00")
        else:
            entries += struct.pack("<HHII", tag, 2, len(val), data_off + len(extra))
            extra += val + (b"\x00" if len(val) % 2 else b"")
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", n) + entries + b"\x00\x00\x00\x00" + extra
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def convert_casio_jpeg(data: bytes, model: int = 10) -> tuple[bytes, JpegMeta]:
    """Find Casio's APP2 metadata, decode it and replace it with EXIF.

    APP2 payload = title (ASCII, space padded) followed by 5 bytes:
    year-2000, month, day, hour, minute. Returns the original bytes unchanged
    (with empty metadata) if the segment is missing or the JPEG is odd.
    """
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return data, JpegMeta()
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: no more metadata segments
            break
        seglen = (data[i + 2] << 8) | data[i + 3]
        if marker == 0xE2:
            payload = data[i + 4:i + 2 + seglen]
            if len(payload) < 5:
                break
            t = payload[:-5]
            title = t.decode("latin-1").rstrip(" \x00") if all(b < 0x80 for b in t) else ""
            y, mo, d, h, mi = payload[-5:]
            meta = JpegMeta(title, 2000 + y, mo, d, h, mi)
            out = data[:i] + _exif_blob(meta, model) + data[i + 2 + seglen:]
            return out, meta
        i += 2 + seglen
    return data, JpegMeta()


def find_jpeg_start(data: bytes) -> int:
    return data.find(b"\xff\xd8\xff\xe0")


# ---------------------------------------------------------------- saving
class PhotoWriter:
    """Writes photos as WQV_YYYYMMDD_NN.ext with the photo's time as file time."""

    def __init__(self, outdir: Path) -> None:
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.saved: list[Path] = []

    def _name(self, ts: Optional[dt.datetime], ext: str) -> Path:
        stem = f"WQV_{ts:%Y%m%d}" if ts else "WQV_undated"
        n = 1
        while True:
            p = self.outdir / f"{stem}_{n:02d}{ext}"
            if not p.exists():
                return p
            n += 1

    def _finish(self, path: Path, ts: Optional[dt.datetime], title: str) -> Path:
        if ts:
            t = ts.timestamp()
            os.utime(path, (t, t))
        if title:
            path.with_name(path.stem + "_title.txt").write_text(title + "\n", encoding="utf-8")
        self.saved.append(path)
        return path

    def save_mono(self, photo: MonoPhoto) -> Path:
        path = self._name(photo.timestamp, ".png")
        path.write_bytes(png_grey(W, H, photo.pixels))
        return self._finish(path, photo.timestamp, photo.title)

    def save_jpeg(self, data: bytes, model: int) -> Path:
        jpeg, meta = convert_casio_jpeg(data, model)
        path = self._name(meta.timestamp, ".jpg")
        path.write_bytes(jpeg)
        return self._finish(path, meta.timestamp, meta.title)

    def save_raw(self, name: str, data: bytes) -> Path:
        path = self.outdir / name
        path.write_bytes(data)
        return path
