"""Frame layer shared by every Casio WQV watch.

Every frame on the wire looks like this:

    BOF(C0) [address] [control] [data ...] [check (2 bytes)] EOF(C1)

C0, C1 and 7D inside the frame are escaped as 7D followed by the byte XOR 20h.

The two watch families differ only in the 2-byte check:

* WQV-1 / WQV-2 use a plain 16-bit sum of address, control and data, sent
  high byte first. This is NOT standard IrDA, which is why ordinary IrDA
  stacks and dongles drop every frame these watches send.
  (Documented by Marcus Groeber, https://mgroeber.de/wqvprot.html)
* WQV-3 / WQV-10 use the standard IrDA SIR frame check (CRC-16/X-25),
  sent low byte first.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

BOF = 0xC0
EOF = 0xC1
ESC = 0x7D
XOR = 0x20


class Check(enum.Enum):
    SUM16 = "sum16"  # WQV-1 / WQV-2
    CRC16 = "crc16"  # WQV-3 / WQV-10 (IrDA FCS, CRC-16/X-25)


class FrameError(enum.Enum):
    OK = 0
    TIMEOUT = 1
    READ_ERROR = 2
    CHECK_FAIL = 3
    MALFORMED = 4
    APP_ERROR = 5


def sum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


def crc16_x25(data: bytes, crc: int = 0xFFFF) -> int:
    """IrDA SIR frame check sequence (CRC-16/X-25). Returns the final value."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _escape(body: bytes) -> bytes:
    out = bytearray()
    for b in body:
        if b in (BOF, EOF, ESC):
            out += bytes((ESC, b ^ XOR))
        else:
            out.append(b)
    return bytes(out)


def encode(addr: int, ctrl: int, data: bytes = b"", check: Check = Check.SUM16, repeat_bof: int = 1) -> bytes:
    body = bytes((addr & 0xFF, ctrl & 0xFF)) + bytes(data)
    if check is Check.SUM16:
        s = sum16(body)
        body += bytes(((s >> 8) & 0xFF, s & 0xFF))
    else:
        c = crc16_x25(body)
        body += bytes((c & 0xFF, (c >> 8) & 0xFF))
    return bytes([BOF] * max(1, repeat_bof)) + _escape(body) + bytes((EOF,))


@dataclass
class Frame:
    error: FrameError = FrameError.OK
    addr: int = 0
    ctrl: int = 0
    data: bytes = b""
    raw: bytes = b""

    @property
    def ok(self) -> bool:
        return self.error is FrameError.OK

    # Aliases used by the WQV-3/10 code, which calls these "port" and "seq"
    @property
    def port(self) -> int:
        return self.addr

    @property
    def seq(self) -> int:
        return self.ctrl

    def __str__(self) -> str:
        if not self.ok:
            return f"<{self.error.name}>"
        return f"{self.addr:02x} {self.ctrl:02x}  {self.data.hex(' ')}"


def decode(raw: bytes, check: Check) -> Frame:
    """Decode one frame. `raw` runs up to and including EOF.

    Leading noise (0xFF padding, line garbage) and repeated BOFs are skipped.
    """
    i = raw.rfind(bytes((BOF,)))
    if i < 0:
        return Frame(FrameError.READ_ERROR, raw=raw)
    # rfind found the LAST BOF; that is the one right before the frame body,
    # because BOF can never appear unescaped inside a body.
    body_esc = raw[i + 1:]
    if body_esc.endswith(bytes((EOF,))):
        body_esc = body_esc[:-1]
    if EOF in body_esc:
        return Frame(FrameError.MALFORMED, raw=raw)
    body = bytearray()
    j = 0
    while j < len(body_esc):
        b = body_esc[j]
        if b == ESC:
            if j + 1 >= len(body_esc):
                return Frame(FrameError.MALFORMED, raw=raw)
            j += 1
            b = body_esc[j] ^ XOR
        body.append(b)
        j += 1
    if len(body) < 4:
        return Frame(FrameError.MALFORMED, raw=raw)
    payload, chk = bytes(body[:-2]), body[-2:]
    if check is Check.SUM16:
        good = ((chk[0] << 8) | chk[1]) == sum16(payload)
    else:
        good = (chk[0] | (chk[1] << 8)) == crc16_x25(payload)
    if not good:
        return Frame(FrameError.CHECK_FAIL, raw=raw)
    return Frame(FrameError.OK, payload[0], payload[1], payload[2:], raw=raw)


@dataclass
class Link:
    """Sends and receives frames over a Transport, with tracing and pacing."""

    transport: "object"
    check: Check
    gap: float = 0.01  # seconds to wait after a received frame before replying
    default_timeout: float = 1.0
    trace: Optional[Callable[[str], None]] = None
    capture: Optional[Callable[[str, str], None]] = None
    _last_rx: float = field(default=0.0, repr=False)

    def send(self, addr: int, ctrl: int, data: bytes = b"", repeat_bof: int = 1) -> None:
        wait = self.gap - (time.monotonic() - self._last_rx)
        if wait > 0:
            time.sleep(wait)
        wire = encode(addr, ctrl, data, self.check, repeat_bof)
        if self.trace or self.capture:
            from .redact import describe_frame
            text = describe_frame(self.check, addr, ctrl, bytes(data), incoming=False)
            if self.trace:
                self.trace("> " + text)
            if self.capture:
                self.capture("tx", text)
        self.transport.write(wire)

    def recv(self, timeout: Optional[float] = None) -> Frame:
        raw = self.transport.read_until_eof(self.default_timeout if timeout is None else timeout)
        self._last_rx = time.monotonic()
        from .redact import describe_frame, describe_raw
        if not raw or raw[-1] != EOF:
            text = "(timeout)" + (f", {describe_raw(raw)}" if raw else "")
            f = Frame(FrameError.TIMEOUT, raw=raw or b"")
        else:
            f = decode(raw, self.check)
            text = describe_frame(self.check, f.addr, f.ctrl, f.data) if f.ok \
                else f"<{f.error.name}> {describe_raw(raw)}"
        if self.trace:
            self.trace("< " + text)
        if self.capture:
            self.capture("rx", text)
        return f

