"""A simulated WQV-1 / WQV-2 watch (Groeber protocol)."""

from __future__ import annotations

from ..frame import Check, Frame, encode
from ..images import MONO_RECORD
from . import SimWatch


class Wqv12Watch(SimWatch):
    check = Check.SUM16

    def __init__(self, records: list[bytes], packet: int = 180, drop_every: int = 0,
                 close_reply: int = 0x61) -> None:
        assert all(len(r) == MONO_RECORD for r in records)
        self.data = b"".join(records)
        self.count = len(records)
        self.packet = packet
        self.drop_every = drop_every
        self.close_reply = close_reply
        self.sid = None
        self.stage = "idle"
        self.offset = 0
        self.expect_get = 0x31
        self.ret = 0x42
        self.last_get = None
        self.last_reply = None
        self.pump_count = 0
        self.closed = False

    def _f(self, addr, ctrl, data=b""):
        return encode(addr, ctrl, data, Check.SUM16)

    def on_frame(self, f: Frame):
        if f.addr == 0xFF and f.ctrl == 0xB3:
            return [self._f(0xFF, 0xA3, bytes((12, 34, 56, 0)))]
        if f.addr == 0xFF and f.ctrl == 0x93:
            self.sid = f.data[4]
            self.stage = "addressed"
            return [self._f(self.sid, 0x63)]
        if f.addr != self.sid:
            return []
        c = f.ctrl
        if c == 0x11 and self.stage == "addressed":
            self.stage = "connected"
            return [self._f(self.sid, 0x01)]
        if c == 0x10 and f.data == b"\x01":
            self.stage = "request"
            return [self._f(self.sid, 0x21)]
        if c == 0x11 and self.stage == "request":
            self.stage = "counted"
            return [self._f(self.sid, 0x20, bytes((0x07, 0xFA, 0x1C, 0x3D, self.count)))]
        if c == 0x32 and f.data == b"\x06":
            self.stage = "pump"
            return [self._f(self.sid, 0x41)]
        if self.stage == "pump" and (c & 0x1F) == 0x11:
            if c == self.last_get and self.last_reply is not None:
                return [self.last_reply]  # host retried: resend the same packet
            if c != self.expect_get:
                return []
            self.pump_count += 1
            chunk = self.data[self.offset:self.offset + self.packet]
            self.offset += len(chunk)
            reply = self._f(self.sid, self.ret, b"\x05" + chunk)
            self.last_get, self.last_reply = c, reply
            self.expect_get = (self.expect_get + 0x20) & 0xFF
            self.ret = 0x40 if self.ret + 2 >= 0x50 else self.ret + 2
            if self.drop_every and self.pump_count % self.drop_every == 0:
                return []  # lose this reply; the host must retry
            return [reply]
        if c == 0x54:
            self.stage = "closing"
            return [self._f(self.sid, self.close_reply)]
        if c == 0x53:
            self.closed = True
            return [self._f(self.sid, 0x63)]
        return []
