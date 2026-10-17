"""Privacy-safe descriptions of frames, for --trace and --capture.

Troubleshooting needs the protocol control bytes (handshakes, commands,
acknowledgements), not people's photos. Every frame that can carry photo
data or photo titles is shortened to a few header bytes plus a count of the
bytes removed:

* WQV-1/2: photo records travel in "05 ..." data frames (title, timestamp
  and pixels). Only the 05 marker is kept.
* WQV-3/10: packets from the watch that start with "<session> 03 00 00" can
  carry JPEG bytes (which include the photo title). They are cut to their
  session header, plus the 18-byte chunk header when there is one (sizes and
  counters only). Protocol packets are kept in full: the app commands
  RIMG/RINF/RCMD, the FIL0 file announcement (camera-made file name), the
  watch's model ID and the IrDA connection setup.
* Frames wqvpad itself sends are never cut: it only sends protocol messages.
* Any other incoming frame over 64 bytes, and any bytes that could not be
  decoded as a frame, are cut too.
"""

from __future__ import annotations

from .frame import Check

KEEP = 8
MAX_PLAIN = 64
APP_COMMANDS = (b"RIMG", b"RINF", b"RCMD")


def _cut(data: bytes, keep: int, what: str) -> str:
    head = data[:keep].hex(" ")
    return f"{head} ..[{len(data) - keep} bytes of {what} removed]".strip()


IRDA_STACK = b"\x19\x36\x66\xbe"   # appears in IrDA connect/setup frames
CHUNK_MAGIC = b"\x00\x20\x03\xff"  # start of a WQV-3/10 chunk header
CHUNK_HEADER = 18


def describe_data(check: Check, data: bytes, incoming: bool = True) -> str:
    n = len(data)
    if not incoming:
        return data.hex(" ")
    if check is Check.SUM16:
        if n > 1 and data[0] == 0x05:
            return _cut(data, 1, "photo data")
    elif n > KEEP and data[1:4] == b"\x03\x00\x00":
        if (data[-4:] in APP_COMMANDS or data[0x42:0x46] == b"FIL0"
                or data[4:8] == IRDA_STACK or data[4:6] == b"\x00\x10"):
            return data.hex(" ")
        keep = 4 + CHUNK_HEADER if data[4:8] == CHUNK_MAGIC else 4
        return _cut(data, min(keep, n), "file data") if n > keep else data[:keep].hex(" ")
    if n > MAX_PLAIN:
        return _cut(data, KEEP, "data")
    return data.hex(" ")


def describe_frame(check: Check, addr: int, ctrl: int, data: bytes, incoming: bool = True) -> str:
    return f"{addr:02x} {ctrl:02x}  len={len(data)}  {describe_data(check, data, incoming)}".rstrip()


def describe_raw(raw: bytes) -> str:
    """Bytes that did not decode as a frame: only their length."""
    return f"{len(raw)} undecodable bytes (contents removed)"
