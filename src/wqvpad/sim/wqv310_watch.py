"""A simulated WQV-3 / WQV-10 watch, scripted from wqv-blink's recorded traces."""

from __future__ import annotations

from typing import Generator, List

from ..frame import Check, Frame, encode
from .. import wqv310 as P
from . import SimWatch


class ScriptError(AssertionError):
    pass


def _need(cond: bool, what: str, f: Frame) -> None:
    if not cond:
        raise ScriptError(f"simulated watch got an unexpected frame ({what}): {f}")


def make_app_cmd(session: int, name: str) -> bytes:
    """An RIMG/RINF/RCMD request, from the recorded WQV-3 trace."""
    sample = bytes.fromhex(
        "09030000002003FF003E107DE1003A580000000034080074031000000008007403000000000008000800800002"
        "434D4430000000060000000100405748543000000006010052494D47")
    d = bytearray(sample)
    d[0] = session
    d[-4:] = name.encode()
    return bytes(d)


def make_fil0(session: int, name: str) -> bytes:
    d = bytearray(0x60)
    d[0:6] = bytes((session, 0x03, 0x00, 0x00, 0x00, 0x20))
    d[0x31] = 0x2A
    d[0x42:0x46] = b"FIL0"
    d[0x4C:0x4C + 12] = name.encode().ljust(12, b"\x00")[:12]
    return bytes(d)


class Wqv310Watch(SimWatch):
    check = Check.CRC16

    def __init__(self, model: int, jpegs: List[bytes], chunk_size: int = 300, frame_size: int = 120,
                 reply_slot: int = 2) -> None:
        assert model in (3, 10)
        self.model = model
        self.jpegs = jpegs
        self.chunk_size = chunk_size
        self.frame_size = frame_size
        self.reply_slot = reply_slot
        self.received_rpl0: list[bytes] = []
        self.finished = False
        self._gen = self._script()
        next(self._gen)

    def on_frame(self, f: Frame):
        if self.finished:
            return []
        try:
            return self._gen.send(f)
        except StopIteration:
            self.finished = True
            return []

    @staticmethod
    def _f(addr, ctrl, data=b""):
        return encode(addr, ctrl, data, Check.CRC16)

    def _script(self) -> Generator[list, Frame, None]:
        F = self._f
        ident = f"CASIO WIC 241{1 if self.model == 3 else 2}/IR".encode()

        # ---- 1. host discovers us and connects as primary
        f = yield []
        while not (f.addr == 0xFF and f.ctrl == 0x3F and f.data[-2] == self.reply_slot):
            _need(f.addr == 0xFF and f.ctrl == 0x3F, "discovery", f)
            f = yield []
        # Recorded reply: 01, watch address 19 36 66 BE, host address, 01 05 00 84 04 00, then the ID string
        xid_reply = bytes((0x01,)) + P.IRDA_STACK + f.data[1:5] + bytes((0x01, 0x05, 0x00, 0x84, 0x04, 0x00)) + ident
        assert xid_reply[15:32] == ident
        f = yield [F(0xFE, 0xBF, xid_reply)]
        _need(f.addr == 0xFF and f.ctrl == 0x93 and f.data[4:8] == P.IRDA_STACK, "SNRM", f)
        wp = f.data[8]
        _need(wp & 0x41 == 0, "host port is even and has the C/R bit clear", f)
        f = yield [F(wp, 0x73, bytes((0x0E, 0x03, 0x00, 0x00)) + P.IRDA_STACK)]
        _need(f.addr == wp + 1 and f.data == P.SESSION_BEGIN, "session begin", f)
        f = yield [F(wp, 0x10, b"\x83")]
        _need(f.data == P.SESSION_NEGOTIATE, "session negotiate", f)
        f = yield [F(wp, 0x21)]
        _need(f.data[:1] == b"\x83" and f.data[2:] == b"\x01\x00\x0e", "session ident", f)
        sess = f.data[1]
        _need(0x4 <= sess < 0xF, "session id range", f)
        f = yield [F(wp, 0x30, bytes((0x80 | sess, 0x03, 0x81, 0x00, 0x01)))]
        _need(not f.data, "ack", f)
        f = yield [F(wp, 0x41)]
        _need(f.data == P.fill(P.CMD_SWAP_ROLES[self.model], sess), "swap roles", f)
        f = yield [F(wp, 0x50, bytes.fromhex("0803010C100400002580110103000104"))]
        f = yield [F(wp, 0x60, bytes.fromhex("080300000D"))]
        f = yield [F(wp, 0x71)]
        _need(f.data == P.fill(P.SESSION_END, sess), "session end", f)
        f = yield [F(wp, 0x81)]
        f = yield [F(wp, 0x91)]
        _need(f.ctrl == 0x53, "disconnect", f)

        # ---- 2. we call the host back as primary
        xid = bytes((0x01,)) + P.IRDA_STACK + b"\xff\xff\xff\xff\x01"
        f = yield [F(wp, 0x73), F(0xFF, 0x3F, xid + b"\x00\x00")]
        _need(f.addr == 0xFE and f.ctrl == 0xBF and f.data[5:9] == P.IRDA_STACK, "host discovery reply", f)
        frames = [F(0xFF, 0x3F, xid + bytes((slot, 0))) for slot in range(1, 6)]
        frames.append(F(0xFF, 0x3F, P.IRDA_IDENT + b"\x00\x8c\x04\x00" + ident))
        HP, WP = 0x70, 0x71
        frames.append(F(0xFF, 0x93, P.IRDA_STACK + bytes((0x0E, 0x03, 0x00, 0x00, HP)) +
                        bytes.fromhex("01013F82010183013F8401018501808601030801FF")))
        f = yield frames
        _need(f.addr == HP and f.ctrl == 0x73, "UA", f)
        f = yield [F(WP, 0x01)]  # a bare ack first; the host should ack back
        _need(f.addr == HP and not f.data, "host ack", f)
        f = yield [F(WP, 0x10, P.CLIENT_SESSION_BEGIN)]
        _need(f.data == P.CLIENT_REPLY_SESSION_BEGIN, "session begin reply", f)
        f = yield [F(WP, 0x32, bytes.fromhex("000184000001000501"))]
        _need(f.data == P.IRDA_NEGOTIATE_1, "negotiate 1", f)
        f = yield [F(WP, 0x34, bytes.fromhex("0001840000010005020006"))]
        _need(f.data == P.IRDA_NEGOTIATE_2, "negotiate 2", f)
        S = 0x09
        f = yield [F(WP, 0x36, bytes((0x80 | S, 0x03, 0x01, 0x00, 0x01)))]
        _need(f.data == P.fill(P.CLIENT_REPLY_SESSIONID_ASSIGN, S), "session id reply", f)
        f = yield [F(WP, 0x98, bytes((S, 0x03, 0x00, 0x03, 0x00, 0x01, 0x04)))]
        f = yield [F(WP, 0x9A, bytes((S, 0x03, 0x00, 0x0C)) + bytes.fromhex("10040000258011010320010C"))]

        # ---- 3. sync
        f = yield [F(WP, 0xB1)]           # host reads this, then acks
        ident_pkt = bytes.fromhex(
            "090300000010000101341004000000000000000008007403000000001166723A330D0A69643A434153494F2057494320"
            "323431312F495220202020200D0A10020000")
        ident_pkt = bytes((S,)) + ident_pkt[1:]
        f = yield [F(WP, 0x9C, ident_pkt)]
        f = yield [F(WP, 0xD1)]
        _need(f.data[:2] == bytes((0x03, S)) and b"LINK QW2411" in f.data, "host identity", f)
        f = yield [F(WP, 0xBE, bytes((S, 0x03, 0x01)))]
        for cmd in ("RIMG", "RINF", "RCMD"):
            pkt = make_app_cmd(S, cmd)
            f = yield [F(WP, 0xB0, pkt)]
            _need(f.data == P.make_response(pkt), f"{cmd} response", f)
            f = yield [F(WP, 0xBE, bytes((S, 0x03, 0x01)))]

        seqs = [0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE]
        for n, jpeg in enumerate(self.jpegs):
            name = f"CIMG{n + 1:04d}.JPG"
            f = yield [F(WP, 0xB0, make_fil0(S, name))]
            _need((f.ctrl & 0xF) == 1 and not f.data, "ack of FIL0", f)
            head = 40  # part of the JPEG travels in the first packet, after a header
            first = bytes((S, 0x03, 0x00, 0x00)) + bytes(range(0x20)) + jpeg[:head]
            f = yield [F(WP, 0x12, first)]
            rest = jpeg[head:]
            chunks = [rest[i:i + self.chunk_size] for i in range(0, len(rest), self.chunk_size)] or [b""]
            k = 0
            for ci, chunk in enumerate(chunks):
                final = ci == len(chunks) - 1
                flags = (0x40 if ci == 0 else 0) | (0x80 if final else 0) | 0x01
                hdr = P.CHUNK_MAGIC + bytes((0x01, 0xFA, 0x10, flags)) + len(chunk).to_bytes(2, "big") \
                    + (ci + 1).to_bytes(4, "big") + (len(chunks) - ci).to_bytes(4, "big")
                pieces = [chunk[i:i + self.frame_size] for i in range(0, len(chunk), self.frame_size)] or [b""]
                for pi, piece in enumerate(pieces):
                    body = bytes((S, 0x03, 0x00, 0x00)) + (hdr if pi == 0 else b"") + piece
                    seq = seqs[k % len(seqs)]
                    k += 1
                    f = yield [F(WP, seq, body)]
                    if seq % 0xF > 8:
                        _need(f.data == bytes((0x03, S, 0x06)), "continue", f)
                    else:
                        _need((f.ctrl & 0xF) == 1 and not f.data, "chunk ack", f)
            f = yield [F(WP, 0xF1)]
            _need(f.data[:2] == bytes((0x03, S)) and b"RPL0" in f.data and name.encode() in f.data, "RPL0", f)
            self.received_rpl0.append(f.data)
            f = yield [F(WP, 0xBE, bytes((S, 0x03, 0x01)))]
        f = yield [F(WP, 0xB0, bytes((S, 0x03, 0x00, 0x00, 0x00, 0x30)))]
        _need((f.ctrl & 0xF) == 1, "final ack", f)
        self.finished = True
        yield []
