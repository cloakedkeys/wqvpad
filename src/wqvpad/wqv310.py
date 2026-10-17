"""Casio WQV-3 / WQV-10 download protocol.

These watches speak real IrDA framing (CRC-16, IrLAP discovery/connect,
sequence numbers) with Casio's own application commands on top, the same
conversation Casio's WQV Link 2.0/3.0 software had with them.

This is a step-for-step port of partlyhuman's wqv-blink "wqv310" firmware
(MIT licence, https://github.com/partlyhuman/wqv-blink), which was reverse
engineered from captured WQV Link sessions and tested on real watches.

Sequence:
  1. We discover the watch and connect as primary, learn the model, then ask
     it to swap roles and hang up.
  2. The watch calls us back as primary; we answer as Casio's PC software.
  3. The watch pushes every photo as a JPEG (in chunks), one file at a time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Optional

from .frame import Check, Frame, FrameError, Link
from .images import find_jpeg_start

CHECK = Check.CRC16
ABORT_AFTER_RETRIES = 10
SESH = 0xC1  # placeholder for the session number; can never appear for real

IRDA_STACK = bytes((0x19, 0x36, 0x66, 0xBE))
IRDA_IDENT = bytes((0x01, 0x19, 0x36, 0x66, 0xBE, 0xFF, 0xFF, 0xFF, 0xFF, 0x01, 0xFF))

SESSION_BEGIN = bytes((0x80, 0x03, 0x01, 0x00))
SESSION_NEGOTIATE = bytes((0x80, 0x03, 0x02, 0x01))
SESSION_IDENT = bytes((0x83, SESH, 0x01, 0x00, 0x0E))
SESSION_END = bytes((0x83, SESH, 0x02, 0x01))

CMD_SWAP_ROLES = {
    3: bytes((0x03, SESH, 0x00, 0x00, 0x01)),
    10: bytes((0x03, SESH, 0x00, 0x00, 0x01, 0x00, 0x00)),
}

CLIENT_SESSION_BEGIN = bytes((0x80, 0x01, 0x01, 0x00))
CLIENT_REPLY_SESSION_BEGIN = bytes((0x81, 0x00, 0x81, 0x00))
CLIENT_REPLY_SESSIONID_ASSIGN = bytes((0x83, SESH, 0x81, 0x00, 0x0E))
CLIENT_APP_ITER_NEXT = bytes((SESH, 0x03, 0x01))
CLIENT_APP_PACKET = bytes((SESH, 0x03, 0x00, 0x00))
CLIENT_APP_FILES_NEXT = bytes((SESH, 0x03, 0x00, 0x00, 0x00, 0x20))
CLIENT_APP_FILES_DONE = bytes((SESH, 0x03, 0x00, 0x00, 0x00, 0x30))

START_SESSION = bytes((0x19, 0x36, 0x66, 0xBE, 0x00, 0x01, 0x01, 0x02, 0x82, 0x01, 0x01, 0x83, 0x01, 0x3F,
                       0x84, 0x01, 0x0F, 0x85, 0x01, 0x80, 0x86, 0x02, 0x80, 0x03, 0x08, 0x01, 0x07))
CONNECT_STR = bytes((0x0E, 0x03, 0x00, 0x00, 0x19, 0x36, 0x66, 0xBE, 0x01, 0x01, 0x02, 0x82, 0x01, 0x01,
                     0x83, 0x01, 0x3F, 0x84, 0x01, 0x0F, 0x85, 0x01, 0x80, 0x86, 0x02, 0x80, 0x03, 0x08,
                     0x01, 0x04))
IRDA_NEGOTIATE_1 = bytes((0x01, 0x00, 0x84, 0x00, 0x00, 0x01, 0x00, 0x05, 0x01, 0x00, 0x00, 0x00, 0x09))
IRDA_NEGOTIATE_2 = bytes((0x01, 0x00, 0x84, 0x00, 0x00, 0x01, 0x00, 0x05, 0x02, 0x00, 0x06, 0x00, 0x01,
                          0x06, 0x01, 0x01, 0x01))
# Our IrDA nickname as seen by the watch (WQV Link sent "WINDOWS XP")
NICKNAME = b"WQVPAD"

WATCH_IDS = {"CASIO WIC 2411/IR": 3, "CASIO WIC 2412/IR": 10}

RINF_EXTRA = bytes((0x00, 0x00, 0x10, 0xFF, 0xFF, 0x11, 0xFF, 0xFF))
RCMD_EXTRA = bytes((0x00, 0x00, 0x20, 0x00, 0x01, 0x00, 0x01))
RIMG_EXTRA = bytes((0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x08, 0x00, 0x06, 0x00, 0x02, 0x07, 0x08, 0x00,
                    0x06, 0x00, 0x06, 0x40, 0x04, 0xB0, 0x05, 0x00, 0x03, 0xC0, 0x04, 0x00, 0x03, 0x00,
                    0x03, 0x20, 0x02, 0x58, 0x02, 0x80, 0x01, 0xE0, 0x01, 0x40, 0x00, 0xF0, 0x03, 0xC4,
                    0x20, 0x04, 0x01, 0xC4, 0x20, 0x05, 0x00, 0x00, 0x18, 0x00))
RPL0_TEMPLATE = bytes((0, 0, 0x00, 0x00, 0x00, 0x20, 0x03, 0xFF, 0x00, 0x38, 0x10, 0xC1, 0x00, 0x34,
                       0x58, 0x40, 0x00, 0x00, 0x00, 0x2E, 0x08, 0x00, 0x74, 0x03, 0x00, 0x00, 0x00, 0x00,
                       0x08, 0x00, 0x74, 0x03, 0x10, 0x00, 0x00, 0x00, 0x00, 0x08, 0x00, 0x08, 0x00, 0,
                       0x00, 0x01, 0x52, 0x50, 0x4C, 0x30, 0x00, 0x00, 0x00, 0x0E, 0x01, 0x00, 0x00, 0x00,
                       0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))
CHUNK_MAGIC = bytes((0x00, 0x20, 0x03, 0xFF))
CHUNK_HEADER_SIZE = 18
APP_CMD_SIZE = 44


class ProtocolError(Exception):
    pass


def fill(cmd: bytes, session: int) -> bytes:
    return bytes(session if b == SESH else b for b in cmd)


def make_response(data: bytes) -> bytes:
    """Answer an RIMG / RINF / RCMD request the way WQV Link did (a BDY0 reply)."""
    if len(data) < APP_CMD_SIZE:
        raise ProtocolError("app command packet too short")
    cmd = data[-4:].decode("latin-1")
    extra, shift = {"RINF": (RINF_EXTRA, -0x0C), "RCMD": (RCMD_EXTRA, -0x0D), "RIMG": (RIMG_EXTRA, 0x20)}[cmd]
    r = bytearray(data[:APP_CMD_SIZE])
    r[0], r[1] = data[1], data[0]          # [session] 03 -> 03 [session]
    r[0x2B] = 0x01
    r[0x0F] = 0x40
    r[0x18], r[0x20] = data[0x20], data[0x18]
    for k in (0x09, 0x0D, 0x13):
        r[k] = (data[k] + shift) & 0xFF
    r += b"BDY0" + len(extra).to_bytes(4, "big") + extra
    return bytes(r)


def make_fil_reply(data: bytes) -> tuple[str, bytes]:
    """Build the RPL0 answer to a FIL0 (file announcement); also returns the file name."""
    r = bytearray(RPL0_TEMPLATE)
    r[0], r[1] = data[1], data[0]
    r[0x29] = data[0x31]
    name = data[0x4C:0x4C + 12]
    r[0x36:0x36 + len(name)] = name
    return name.decode("latin-1").rstrip("\x00 "), bytes(r)


@dataclass
class ChunkHeader:
    is_initial: bool
    is_final: bool
    size: int
    number: int
    left: int


def parse_chunk_header(payload: bytes) -> Optional[ChunkHeader]:
    if len(payload) < CHUNK_HEADER_SIZE or payload[:4] != CHUNK_MAGIC:
        return None
    flags = payload[7]
    return ChunkHeader(
        is_initial=bool(flags & 0x40),
        is_final=bool(flags & 0x80),
        size=int.from_bytes(payload[8:10], "big"),
        number=int.from_bytes(payload[10:14], "big"),
        left=int.from_bytes(payload[14:18], "big") - 1,
    )


class Wqv310Session:
    def __init__(self, link: Link, progress: Optional[Callable[[str, int, int], None]] = None,
                 on_file: Optional[Callable[[str, bytes, int], None]] = None,
                 rng: Optional[random.Random] = None,
                 discovery_slot: float = 0.05, callback_timeout: float = 5.0) -> None:
        self.link = link
        self.progress = progress or (lambda *_: None)
        self.on_file = on_file or (lambda *_: None)
        self.rng = rng or random.Random()
        self.discovery_slot = discovery_slot
        self.callback_timeout = callback_timeout
        self.our_port = 0xFF
        self.watch_port = 0xFF
        self.model = 0
        self.session = 0
        self.seq_upper = 1
        self.seq_lower = 0
        self.frame = Frame()
        self.watch_firmware = ""
        self.files: list[tuple[str, bytes]] = []

    # ---------------------------------------------------------------- helpers
    def seq(self, data: bool = False, inc_upper: bool = False, inc_lower: bool = False) -> int:
        if inc_upper:
            self.seq_upper += 2
        if inc_lower:
            self.seq_lower += 2
        return ((self.seq_upper & 0xF) << 4) | ((self.seq_lower if data else 1) & 0xF)

    def S(self, cmd: bytes) -> bytes:
        return fill(cmd, self.session)

    def send(self, ctrl: int, data: bytes = b"", addr: Optional[int] = None, repeat_bof: int = 10) -> None:
        self.link.send(self.our_port if addr is None else addr, ctrl, data, repeat_bof)

    def recv(self, timeout: Optional[float] = None) -> Frame:
        self.frame = self.link.recv(timeout)
        return self.frame

    def expect(self, port: int, seq: int, min_len: int = -1) -> bool:
        f = self.frame
        return f.ok and f.port == port and f.seq == seq and (min_len < 0 or len(f.data) >= min_len)

    def expect_ack(self) -> bool:
        f = self.frame
        return f.ok and f.port == self.watch_port and (f.seq & 0xF) == 1 and not f.data

    def starts_with(self, prefix: bytes) -> bool:
        return self.frame.ok and self.frame.data[:len(prefix)] == prefix

    def exactly(self, data: bytes) -> bool:
        return self.frame.ok and self.frame.data == data

    def fail(self, what: str):
        raise ProtocolError(f"{what} (last frame: {self.frame})")

    def ack_until_data(self) -> Frame:
        """Keep acknowledging the watch until it sends a frame with data."""
        for _ in range(ABORT_AFTER_RETRIES + 1):
            self.recv()
            if not self.frame.ok:
                self.send(self.seq())  # ask for a resend
                continue
            if self.frame.seq == 0x53:
                self.frame = Frame(FrameError.APP_ERROR)
                return self.frame
            if self.frame.port == self.watch_port:
                if self.frame.data:
                    return self.frame
                self.send(self.seq())
        self.frame = Frame(FrameError.TIMEOUT)
        return self.frame

    def _rand4(self) -> bytes:
        return bytes(self.rng.randrange(256) & ~0b11000001 & 0xFF for _ in range(4))

    # ---------------------------------------------------------------- step 1
    def open_session(self) -> bool:
        """Discover the watch. Returns False quickly if nothing answers, so callers can poll."""
        self.watch_port = self.rng.randrange(256) & 0xBE
        self.our_port = self.watch_port + 1
        addr = self._rand4()
        xid = bytearray(b"\x01" + addr + b"\xff\xff\xff\xff\x01\x00\x00")
        found = False
        for slot in range(6):
            xid[-2] = slot
            self.send(0x3F, bytes(xid), addr=0xFF, repeat_bof=11)
            self.recv(self.discovery_slot)
            if self.expect(0xFE, 0xBF, 32):
                found = True
                break
        if not found:
            return False

        ident = self.frame.data[15:32].decode("latin-1", "replace")
        if ident not in WATCH_IDS:
            raise ProtocolError(f"unrecognised device answered: {ident!r}")
        self.model = WATCH_IDS[ident]
        self.progress("connect", 1, 5)

        snrm = bytearray(addr + START_SESSION)
        snrm[len(addr) + 4] = self.watch_port
        self.send(0x93, bytes(snrm), addr=0xFF)
        if not self.recv().ok:
            self.fail("watch did not accept the connection")

        self.seq_upper, self.seq_lower = 1, 0
        self.send(self.seq(True), self.S(SESSION_BEGIN))
        if not self.recv().ok:
            self.fail("no reply to session begin")

        self.send(self.seq(True, True, True), self.S(SESSION_NEGOTIATE))
        self.recv()
        if not self.expect_ack():
            self.fail("session negotiation not acknowledged")

        self.session = self.rng.randrange(0x4, 0xF)
        self.send(self.seq(True, False, True), self.S(SESSION_IDENT))
        self.recv()
        if not self.frame.ok or len(self.frame.data) < 2:
            self.fail("session id not confirmed")

        self.send(self.seq(False, True, False))
        self.recv()  # ack, not essential
        return True

    def close_session(self) -> None:
        self.send(self.seq(True, False, True), self.S(SESSION_END))
        self.recv()
        self.send(self.seq(False, False, True))
        self.recv()
        self.send(0x53)
        self.recv()

    def swap_roles_and_close(self) -> None:
        cmd = CMD_SWAP_ROLES.get(self.model)
        if cmd is None:
            self.fail(f"unknown model {self.model}")
        self.send(self.seq(True, False, True), self.S(cmd))
        self.recv()
        self.send(self.seq(False, True, False))
        self.recv()
        self.send(self.seq(False, True, False))
        self.recv()
        self.close_session()
        self.progress("connect", 2, 5)

    # ---------------------------------------------------------------- step 2
    def open_session_client_role(self) -> None:
        self.watch_port, self.our_port = 0xFF, 0xFE
        self.seq_lower, self.seq_upper = 0, 1

        self.recv(self.callback_timeout)
        if self.frame.error is FrameError.TIMEOUT:
            self.fail("the watch did not call back after the role swap")

        hi = b"\x01" + self._rand4() + IRDA_STACK + b"\x01\x05\x00\x84\x25\x00" + NICKNAME + b"\x00"
        self.send(0xBF, hi)

        while True:
            self.recv()
            if not self.frame.ok:
                self.fail("lost the watch during discovery")
            if self.starts_with(IRDA_IDENT):
                break

        self.recv()
        if not self.starts_with(IRDA_STACK) or len(self.frame.data) < 9:
            self.fail("expected the watch's connect request")
        self.our_port = self.frame.data[8]
        self.watch_port = (self.our_port + 1) & 0xFF
        self.progress("connect", 3, 5)

        self.send(0x73, CONNECT_STR)

        self.ack_until_data()
        if not self.starts_with(CLIENT_SESSION_BEGIN):
            self.fail("expected session begin from the watch")
        self.send(self.seq(True, True, False), CLIENT_REPLY_SESSION_BEGIN)

        negotiations = 0
        for i in range(ABORT_AFTER_RETRIES + 2):
            if i > ABORT_AFTER_RETRIES:
                self.fail("session id never assigned")
            self.recv()
            if not self.frame.ok:
                self.fail("lost the watch while negotiating")
            d = self.frame.data
            if len(d) == 5 and 0x80 < d[0] <= 0x8F:
                self.session = d[0] & 0xF
                self.send(self.seq(True, True, True), self.S(CLIENT_REPLY_SESSIONID_ASSIGN))
                break
            elif self.starts_with(b"\x00\x01\x84"):
                if negotiations > 1:
                    self.fail("unexpected extra IrDA negotiation")
                self.send(self.seq(True, True, True), (IRDA_NEGOTIATE_1, IRDA_NEGOTIATE_2)[negotiations])
                negotiations += 1
            elif (self.frame.seq & 0xF) == 1:
                self.send(self.seq())
            else:
                self.fail("unexpected frame while negotiating")

        self.recv()
        if not self.starts_with(bytes((self.session, 0x03, 0x00, 0x03))):
            self.fail("expected session parameters (03)")
        self.send(self.seq(False, True, False))

        self.recv()
        if not self.starts_with(bytes((self.session, 0x03, 0x00, 0x0C))):
            self.fail("expected session parameters (0C)")
        self.send(self.seq(False, True, False))
        self.progress("connect", 4, 5)

    # ---------------------------------------------------------------- step 3
    def _answer_app_command(self, name: str) -> None:
        self.ack_until_data()
        if not (self.starts_with(self.S(CLIENT_APP_PACKET)) and self.frame.data[-4:] == name.encode()):
            self.fail(f"expected {name} command")
        self.send(self.seq(True, True, True), make_response(self.frame.data))
        self._expect_iter_next()

    def _expect_iter_next(self) -> None:
        self.ack_until_data()
        if not self.exactly(self.S(CLIENT_APP_ITER_NEXT)):
            self.fail("expected 'next'")
        self.send(self.seq(False, True, False))

    def sync(self) -> list[tuple[str, bytes]]:
        self.recv()  # whatever the watch sends first

        self.send(self.seq())
        self.ack_until_data()
        if not self.starts_with(bytes((self.session, 0x03, 0x00, 0x00, 0x00, 0x10))):
            self.fail("expected the watch's identity")
        self.watch_firmware = self.frame.data[0x26:0x26 + 0x16].split(b"\x00")[0].decode("latin-1").strip()
        self.send(self.seq(False, True, False))

        self.recv()
        if not self.expect_ack():
            self.fail("identity not acknowledged")
        fw_ident = bytes((0x03, self.session, 0x00, 0x00, 0x00, 0x11, 0x01, 0x30, 0x10, 0x04, 0x08, 0x00, 0x74,
                          0x03, 0x00, 0x00, 0x00, 0x00, 0x08, 0x00, 0x74, 0x03, 0x10, 0x00, 0x00, 0x00, 0x11)) \
            + b"fr:1\r\nid:LINK QW2411       \r\n"
        self.send(self.seq(True, False, True), fw_ident)
        self._expect_iter_next()

        for cmd in ("RIMG", "RINF", "RCMD"):
            self._answer_app_command(cmd)
        self.progress("connect", 5, 5)

        self.files = []
        while True:
            self.ack_until_data()
            if self.starts_with(self.S(CLIENT_APP_FILES_DONE)):
                self.send(self.seq(False, True, False))
                break
            if not self.starts_with(self.S(CLIENT_APP_FILES_NEXT)):
                self.fail("expected a file announcement")
            name, rpl0 = make_fil_reply(self.frame.data)
            self.send(self.seq(False, True, False))
            data = self._receive_file(len(self.files))
            self.files.append((name, data))
            self.on_file(name, data, self.model)

            self.recv()
            if not self.expect_ack():
                self.fail("expected acknowledgement after the file")
            self.send(self.seq(True, False, True), rpl0)
            self._expect_iter_next()

        self.ack_until_data_quiet()
        return self.files

    def _receive_file(self, index: int) -> bytes:
        buf = bytearray()
        self.recv()
        if not self.starts_with(self.S(CLIENT_APP_PACKET)):
            self.fail("expected the first file packet")
        start = find_jpeg_start(self.frame.data)
        if start >= 0:
            buf += self.frame.data[start:]
        self.send(self.seq(False, True, False))

        while True:  # chunks in file
            frame_num = 0
            got = 0
            header: Optional[ChunkHeader] = None
            while True:  # frames in chunk
                self.recv()
                if not self.starts_with(self.S(CLIENT_APP_PACKET)):
                    self.fail("expected a file data packet")
                payload = self.frame.data[len(CLIENT_APP_PACKET):]
                if frame_num == 0:
                    header = parse_chunk_header(payload)
                    if header is None:
                        self.fail("chunk header not found")
                    payload = payload[CHUNK_HEADER_SIZE:]
                got += len(payload)
                buf += payload
                self.progress(f"photo {index + 1}", len(buf), 0)
                # Periodically say "continue", otherwise a normal ack (as WQV Link did)
                if self.frame.seq % 0xF > 8:
                    self.send(self.seq(True, True, True), bytes((0x03, self.session, 0x06)))
                else:
                    self.send(self.seq(False, True, False))
                frame_num += 1
                if got >= header.size:
                    break
            if header.is_final:
                return bytes(buf)

    def ack_until_data_quiet(self) -> None:
        """After the last file the watch hangs up; absorb whatever is left."""
        old = self.link.default_timeout
        try:
            self.link.default_timeout = 0.25
            self.ack_until_data()
        finally:
            self.link.default_timeout = old

    def run(self) -> list[tuple[str, bytes]]:
        """Everything after a successful open_session()."""
        self.swap_roles_and_close()
        self.open_session_client_role()
        return self.sync()
