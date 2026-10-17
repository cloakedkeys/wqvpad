"""Casio WQV-1 / WQV-2 download protocol.

Protocol reverse engineered by Marcus Groeber (https://mgroeber.de/wqvprot.html)
and refined against real watches by Roger Braunstein (partlyhuman) in
wqv-blink (MIT licence), which this module follows step for step.

On the watch, choose IR Comm and the PC transfer option; the PC then drives
the whole exchange.
"""

from __future__ import annotations

import random
from typing import Callable, Optional

from .frame import Check, Frame, Link
from .images import MONO_RECORD, MonoPhoto, split_mono_dump

ABORT_AFTER_RETRIES = 10
CHECK = Check.SUM16


class ProtocolError(Exception):
    pass


class Wqv12Session:
    def __init__(self, link: Link, progress: Optional[Callable[[str, int, int], None]] = None,
                 rng: Optional[random.Random] = None) -> None:
        self.link = link
        self.progress = progress or (lambda *_: None)
        self.rng = rng or random.Random()
        self.session_id = 0xFF
        self.watch_time: bytes = b""
        self.frame = Frame()

    # ---------------------------------------------------------------- helpers
    def send_recv(self, addr: int, ctrl: int, data: bytes = b"", retries: int = 5,
                  timeout: Optional[float] = None) -> bool:
        """Send a frame and wait for a valid reply. Every send gets a reply."""
        for _ in range(retries):
            self.link.send(addr, ctrl, data)
            self.frame = self.link.recv(timeout)
            if self.frame.ok:
                return True
        return False

    def expect(self, addr: int, ctrl: int, min_len: int = -1) -> bool:
        f = self.frame
        return f.ok and f.addr == addr and f.ctrl == ctrl and (min_len < 0 or len(f.data) >= min_len)

    # ---------------------------------------------------------------- phases
    def open_session(self) -> bool:
        """Handshake. Returns False quickly if no watch answers, so callers can poll."""
        self.session_id = 0xFF
        # > FF B3   "anyone there?"
        self.send_recv(0xFF, 0xB3, retries=1, timeout=0.2)
        # < FF A3  hh mm ss ff
        if not self.expect(0xFF, 0xA3, 4):
            return False
        self.watch_time = self.frame.data[:4]

        # Pick an address; avoid 0 and anything that would need escaping
        self.session_id = self.rng.randrange(0x1A) + 1
        hello = bytes(self.frame.data[:4]) + bytes((self.session_id,))
        self.progress("connect", 1, 3)

        for i in range(ABORT_AFTER_RETRIES + 1):
            # > FF 93  hh mm ss ff <adr>
            self.send_recv(0xFF, 0x93, hello, retries=1)
            # < <adr> 63   (the watch may repeat earlier replies first)
            if self.expect(self.session_id, 0x63):
                break
        else:
            return False
        self.progress("connect", 2, 3)

        for i in range(ABORT_AFTER_RETRIES + 1):
            # > <adr> 11
            self.send_recv(self.session_id, 0x11)
            # < <adr> 01
            if self.expect(self.session_id, 0x01):
                break
        else:
            return False
        self.progress("connect", 3, 3)
        return True

    def download_dump(self) -> bytes:
        """Ask for all photos; returns the raw concatenated photo records."""
        sid = self.session_id
        # > <adr> 10 01        < <adr> 21
        self.send_recv(sid, 0x10, b"\x01")
        if not self.expect(sid, 0x21):
            raise ProtocolError("watch did not accept the download request (10 01)")
        # > <adr> 11           < <adr> 20  07 FA 1C 3D <count>
        self.send_recv(sid, 0x11)
        if not self.expect(sid, 0x20, 5):
            raise ProtocolError("watch did not report its photo count")
        count = self.frame.data[4]
        # > <adr> 32 06        < <adr> 41
        self.send_recv(sid, 0x32, b"\x06")
        if not self.expect(sid, 0x41):
            raise ProtocolError("watch did not start the transfer (32 06)")

        total = count * MONO_RECORD
        dump = bytearray()
        get_num, ret_num = 0x31, 0x42
        retries = 0
        self.progress("download", 0, total)
        while len(dump) < total:
            if retries > ABORT_AFTER_RETRIES:
                raise ProtocolError(f"transfer aborted after {ABORT_AFTER_RETRIES} retries "
                                    f"({len(dump)}/{total} bytes)")
            # > <adr> <get>          < <adr> <ret> 05 <data...>
            if not self.send_recv(sid, get_num, retries=1):
                retries += 1
                continue
            if not self.expect(sid, ret_num) or not self.frame.data or self.frame.data[0] != 0x05:
                retries += 1
                continue
            retries = 0
            dump += self.frame.data[1:]
            get_num = (get_num + 0x20) & 0xFF   # 31, 51, 71 ... F1, 11, 31 ...
            ret_num += 2                        # 42, 44 ... 4E, 40, 42 ...
            if ret_num >= 0x50:
                ret_num = 0x40
            self.progress("download", min(len(dump), total), total)
        return bytes(dump[:total])

    def close_session(self) -> bool:
        sid = self.session_id
        # > <adr> 54 06        < <adr> 61   (some watches answer 43)
        self.send_recv(sid, 0x54, b"\x06")
        if not (self.expect(sid, 0x43) or self.expect(sid, 0x61)):
            return False
        # > <adr> 53           < <adr> 63
        self.send_recv(sid, 0x53)
        ok = self.expect(sid, 0x63)
        self.session_id = 0xFF
        return ok

    def run(self) -> tuple[list[MonoPhoto], bytes]:
        """Full download after a successful open_session()."""
        dump = self.download_dump()
        self.close_session()  # a clean goodbye is nice but not required
        return split_mono_dump(dump), dump
