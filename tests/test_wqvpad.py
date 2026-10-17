import random
import struct

import pytest

from wqvpad import wqv12, wqv310
from wqvpad.core import Options, download
from wqvpad.frame import Check, FrameError, Link, crc16_x25, decode, encode, sum16
from wqvpad.images import (MONO_RECORD, convert_casio_jpeg, parse_mono_record, png_grey, split_mono_dump)
from wqvpad.sim import SimTransport
from wqvpad.sim.samples import demo_jpegs, mono_record
from wqvpad.sim.wqv12_watch import Wqv12Watch
from wqvpad.sim.wqv310_watch import Wqv310Watch


# ------------------------------------------------------------------ frames
def test_crc16_x25_standard_check_value():
    assert crc16_x25(b"123456789") == 0x906E


def test_sum16_example_from_groeber():
    # ">  FFh B3h" frame: checksum is FF + B3 = 01B2, high byte first
    assert encode(0xFF, 0xB3, b"", Check.SUM16) == bytes((0xC0, 0xFF, 0xB3, 0x01, 0xB2, 0xC1))


@pytest.mark.parametrize("check", list(Check))
def test_roundtrip_with_escaping(check):
    data = bytes(range(256)) + b"\xc0\xc1\x7d"
    wire = encode(0xC0, 0x7D, data, check, repeat_bof=10)
    assert wire.count(b"\xc1") == 1 and wire.endswith(b"\xc1")
    f = decode(b"\xff\xff" + wire, check)
    assert f.ok and f.addr == 0xC0 and f.ctrl == 0x7D and f.data == data


def test_crc_frame_matches_wqv_blink_layout():
    # Little-endian CRC after the body, per wqv-blink frame.cpp
    wire = encode(0x01, 0x02, b"\x03", Check.CRC16)
    c = crc16_x25(b"\x01\x02\x03")
    assert wire == bytes((0xC0, 1, 2, 3, c & 0xFF, c >> 8, 0xC1))


def test_bad_check_rejected():
    wire = bytearray(encode(1, 2, b"abc", Check.SUM16))
    wire[3] ^= 1
    assert decode(bytes(wire), Check.SUM16).error is FrameError.CHECK_FAIL
    # A WQV-1 frame is NOT valid IrDA, which is why standard stacks drop it
    assert not decode(encode(1, 2, b"abc", Check.SUM16), Check.CRC16).ok


# ------------------------------------------------------------------ images
def test_mono_record_layout_and_nibble_order():
    rec = bytearray(MONO_RECORD)
    rec[:24] = b"HELLO".ljust(24, b" ")
    rec[24:29] = bytes((1, 2, 3, 4, 5))
    rec[29] = 0xF0  # pixel0 = low nibble 0 (white), pixel1 = high nibble F (black)
    p = parse_mono_record(bytes(rec))
    assert p.title == "HELLO" and (p.year, p.month, p.day, p.hour, p.minute) == (2001, 2, 3, 4, 5)
    assert p.pixels[0] == 255 and p.pixels[1] == 0
    assert MONO_RECORD == 0x1C3D


def test_png_is_valid():
    from PIL import Image
    import io
    png = png_grey(3, 2, bytes([0, 128, 255, 10, 20, 30]))
    im = Image.open(io.BytesIO(png))
    assert im.size == (3, 2) and list(im.tobytes()) == [0, 128, 255, 10, 20, 30]


def test_jpeg_metadata_becomes_exif_and_scan_is_untouched():
    from PIL import Image
    import io
    src = demo_jpegs()[0]
    out, meta = convert_casio_jpeg(src, 10)
    assert meta.title == "DEMO 1" and meta.timestamp.isoformat() == "2001-07-14T09:30:00"
    assert b"\xff\xe2" not in out[:200]
    sos = src.index(b"\xff\xda")
    assert out.endswith(src[sos:])  # compressed image data identical
    ex = Image.open(io.BytesIO(out)).getexif()
    assert ex[0x0132] == "2001:07:14 09:30:00" and ex[0x010F] == "Casio" and ex[0x0110] == "WQV-10"
    assert ex[0x010E] == "DEMO 1"


def test_jpeg_without_casio_segment_passes_through():
    jfif = demo_jpegs()[0]
    plain = jfif[:jfif.index(b"\xff\xe2")] + jfif[jfif.index(b"\xff\xe2") + 2 + 31:]
    out, meta = convert_casio_jpeg(plain)
    assert out == plain and meta.title == ""


# ------------------------------------------------------------------ WQV-3/10 app layer
def test_make_response_matches_recorded_rules():
    from wqvpad.sim.wqv310_watch import make_app_cmd
    pkt = make_app_cmd(9, "RIMG")
    r = wqv310.make_response(pkt)
    assert r[:2] == bytes((0x03, 0x09)) and r[0x2B] == 1 and r[0x0F] == 0x40
    assert r[0x18] == pkt[0x20] and r[0x20] == pkt[0x18]
    assert r[0x09] == (pkt[0x09] + 0x20) & 0xFF
    assert r[44:48] == b"BDY0" and int.from_bytes(r[48:52], "big") == len(wqv310.RIMG_EXTRA)
    rinf = wqv310.make_response(make_app_cmd(9, "RINF"))
    assert rinf[0x09] == (pkt[0x09] - 0x0C) & 0xFF


def test_fil_reply():
    from wqvpad.sim.wqv310_watch import make_fil0
    name, rpl = wqv310.make_fil_reply(make_fil0(5, "CIMG0001.JPG"))
    assert name == "CIMG0001.JPG" and rpl[:2] == bytes((3, 5)) and rpl[0x29] == 0x2A
    assert rpl[0x36:0x42] == b"CIMG0001.JPG" and b"RPL0" in rpl and len(rpl) == len(wqv310.RPL0_TEMPLATE)


def test_host_identity_bytes_match_wqv_blink():
    # FW_IDENT tail in wqv-blink main.cpp, as hex
    tail = bytes.fromhex("66723A310D0A69643A4C494E4B205157323431312020202020202020200D0A")
    assert tail.startswith(b"fr:1\r\nid:LINK QW2411")


# ------------------------------------------------------------------ full sessions
def _opts(tmp_path, **kw):
    return Options(outdir=tmp_path, wait=5, gap=0, timeout=0.2, status=lambda *_: None, **kw)


def _records(n):
    return [mono_record(f"PIC{k}", (1, 6, 1 + k, 10, k), k) for k in range(n)]


@pytest.mark.parametrize("echo", [False, True])
def test_wqv12_full_download(tmp_path, echo):
    recs = _records(3)
    watch = Wqv12Watch(recs)
    res = download(SimTransport(watch, echo=echo), _opts(tmp_path, keep_raw=True))
    assert res.model == 12 and len(res.saved) == 3 and watch.closed
    assert (tmp_path / "wqv12_dump.bin").read_bytes() == b"".join(recs)
    from PIL import Image
    im = Image.open(res.saved[0])
    assert im.size == (120, 120) and im.mode == "L"


def test_wqv12_recovers_from_lost_packets(tmp_path):
    recs = _records(2)
    watch = Wqv12Watch(recs, drop_every=7, close_reply=0x43)
    res = download(SimTransport(watch), _opts(tmp_path, keep_raw=True, model="1"))
    assert (tmp_path / "wqv12_dump.bin").read_bytes() == b"".join(recs)


def test_wqv12_packet_counters_wrap(tmp_path):
    # Enough packets to wrap both the 31,51..F1,11 and 42..4E,40 sequences several times
    recs = _records(4)
    watch = Wqv12Watch(recs, packet=64)
    res = download(SimTransport(watch), _opts(tmp_path, keep_raw=True))
    assert watch.pump_count > 400
    assert (tmp_path / "wqv12_dump.bin").read_bytes() == b"".join(recs)


@pytest.mark.parametrize("model", [3, 10])
@pytest.mark.parametrize("chunk,frame", [(300, 120), (1000, 250), (64, 64), (5000, 90)])
def test_wqv310_full_download(tmp_path, model, chunk, frame):
    jpegs = demo_jpegs()
    watch = Wqv310Watch(model, jpegs, chunk_size=chunk, frame_size=frame)
    res = download(SimTransport(watch), _opts(tmp_path, keep_raw=True))
    assert res.model == model and len(res.saved) == 2 and watch.finished
    assert len(watch.received_rpl0) == 2
    for path, src in zip(res.saved, jpegs):
        out = path.read_bytes()
        sos = src.index(b"\xff\xda")
        assert out.endswith(src[sos:])


def test_wqv310_with_echo_and_line_noise(tmp_path):
    watch = Wqv310Watch(10, demo_jpegs())
    res = download(SimTransport(watch, echo=True, noise=b"\xff\xff\x00"), _opts(tmp_path))
    assert len(res.saved) == 2


def test_forced_model_family(tmp_path):
    watch = Wqv310Watch(3, demo_jpegs()[:1])
    res = download(SimTransport(watch), _opts(tmp_path, model="3"))
    assert res.model == 3 and len(res.saved) == 1


def test_no_watch(tmp_path):
    from wqvpad.core import NoWatch
    from wqvpad.sim import SimWatch

    class Silent(SimWatch):
        def on_frame(self, f):
            return []

    o = _opts(tmp_path)
    o.wait = 0.5
    with pytest.raises(NoWatch):
        download(SimTransport(Silent()), o)


# ------------------------------------------------------------------ transports
def test_serial_pod_lines_and_echo_suppression():
    from wqvpad.transport.serial_pod import SerialPod
    pod = SerialPod("loop://", baud=115200)
    assert pod._ser.dtr and pod._ser.rts and pod._ser.baudrate == 115200
    wire = encode(0xFF, 0xB3, b"", Check.SUM16)
    pod.write(wire)  # loop:// echoes everything, like a pod that sees its own light
    assert pod.read_until_eof(0.2) == b""
    pod.close()


class FakeUsbDevice:
    """Records what the PAD-5 code sends to the STIr4200."""

    def __init__(self, rx_chunks=()):
        self.regs = {}
        self.writes = []
        self.reg_log = []
        self.rx = list(rx_chunks)
        self.bus, self.address = 1, 7

    def set_configuration(self):
        pass

    def clear_halt(self, ep):
        pass

    def ctrl_transfer(self, bm, req, value, index, data_or_len, timeout):
        if bm == 0x40 and req == 0x03:
            self.regs[index] = value
            self.reg_log.append((index, value))
            return 0
        if bm == 0xC0 and req == 0x01:
            if index == 5:
                return bytes((0x04, 0, 0))  # FIFO empty
            return bytes(self.regs.get(index + i, 0) for i in range(data_or_len))
        raise AssertionError((bm, req))

    def write(self, ep, data, timeout):
        assert ep == 0x01
        self.writes.append(bytes(data))
        return len(data)

    def read(self, ep, size, timeout):
        import usb.core
        assert ep == 0x82
        if self.rx:
            return self.rx.pop(0)
        raise usb.core.USBTimeoutError("timeout")


def test_pad5_init_sequence_and_framing(monkeypatch):
    import usb.util
    from wqvpad.transport import stir4200
    reply = encode(0xFF, 0xA3, bytes((0x0C, 0x22, 0x38, 0x00)), Check.SUM16)
    dev = FakeUsbDevice(rx_chunks=[reply[:3], reply[3:]])  # arrives split across USB reads
    monkeypatch.setattr(stir4200, "find_pad5_devices", lambda: [dev])
    monkeypatch.setattr(usb.util, "claim_interface", lambda d, i: None)
    monkeypatch.setattr(usb.util, "release_interface", lambda d, i: None)
    monkeypatch.setattr(usb.util, "dispose_resources", lambda d: None)
    pad = stir4200.Pad5()
    # reset, DPLL, 115200 clock, SIR mode, SD pulse, ctrl1, sensitivity
    assert dev.reg_log == [(3, 0x01), (8, 0x15), (2, 0x09), (1, 0x2A), (3, 0x80), (3, 0x00), (4, 0x20)]
    wire = encode(0xFF, 0xB3, b"", Check.SUM16)
    pad.write(wire)
    assert dev.writes == [bytes((0x55, 0xAA, len(wire), 0)) + wire]
    link = Link(pad, Check.SUM16, gap=0)
    f = link.recv(0.5)
    assert f.ok and f.addr == 0xFF and f.ctrl == 0xA3 and f.data == bytes((0x0C, 0x22, 0x38, 0x00))
    pad.close()
    assert dev.reg_log[-1] == (3, 0x18)  # transceiver powered down


def test_pad1_litelink_reset_pulses_rts(monkeypatch):
    import serial
    from wqvpad.transport.serial_pod import SerialPod
    log = []
    real = serial.serial_for_url

    def recording(url, **kw):
        s = real(url, **kw)
        cls = type(s)

        class Rec(cls):
            def _update_dtr_state(self):
                log.append(("dtr", self._dtr_state)); super()._update_dtr_state()

            def _update_rts_state(self):
                log.append(("rts", self._rts_state)); super()._update_rts_state()
        s.__class__ = Rec
        return s

    monkeypatch.setattr(serial, "serial_for_url", recording)
    pod = SerialPod("loop://", litelink_reset=True)
    rts = [v for k, v in log if k == "rts"]
    # ends high, after a low pulse
    assert rts[-1] is True and False in rts and rts[rts.index(False) + 1] is True
    assert pod._ser.dtr and pod._ser.rts
    pod.close()


# ------------------------------------------------------------------ PAD-5 driver setup
def _fake_windows(monkeypatch, tmp_path, returncode):
    import subprocess
    from wqvpad import driver
    exe = tmp_path / "wdi-simple.exe"
    exe.write_bytes(b"")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout="log line\n", stderr="")

    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver.subprocess, "run", run)
    return driver, exe, calls


def test_driver_install_runs_wdi_simple_for_pad5_only(monkeypatch, tmp_path):
    driver, exe, calls = _fake_windows(monkeypatch, tmp_path, 0)
    said = []
    assert driver.install_pad5_driver(say=said.append, ask=lambda q: True, installer=exe)
    cmd = calls[0]
    assert cmd[0] == str(exe)
    assert cmd[cmd.index("--vid") + 1] == "0x066F" and cmd[cmd.index("--pid") + 1] == "0x4200"
    assert cmd[cmd.index("--type") + 1] == "0"  # WinUSB
    assert any("administrator" in s for s in said)


def test_driver_install_reports_declined_prompt(monkeypatch, tmp_path):
    driver, exe, calls = _fake_windows(monkeypatch, tmp_path, (1 << 32) - 14)  # -14 as Windows reports it
    said = []
    assert not driver.install_pad5_driver(say=said.append, installer=exe)
    assert any("declined" in s for s in said)


def test_driver_install_can_be_skipped(monkeypatch, tmp_path):
    driver, exe, calls = _fake_windows(monkeypatch, tmp_path, 0)
    assert not driver.install_pad5_driver(say=lambda s: None, ask=lambda q: False, installer=exe)
    assert calls == []


def test_driver_step_not_needed_off_windows(monkeypatch):
    from wqvpad import driver
    monkeypatch.setattr(driver, "is_windows", lambda: False)
    assert driver.install_pad5_driver(say=lambda s: None)


# ------------------------------------------------------------------ privacy of captures
def _capture_text(tmp_path, watch, **kw):
    lines = []
    o = _opts(tmp_path, **kw)
    o.capture = lambda d, t: lines.append(f"{d} {t}")
    o.trace = lambda t: lines.append(f"trace {t}")
    download(SimTransport(watch), o)
    return "\n".join(lines)


def _hex(b: bytes) -> str:
    return b.hex(" ")


@pytest.mark.parametrize("model", [3, 10])
def test_capture_has_no_photo_data_or_titles_wqv310(tmp_path, model):
    jpegs = demo_jpegs()
    text = _capture_text(tmp_path, Wqv310Watch(model, jpegs))
    assert "ff d8 ff" not in text                       # no JPEG start
    assert _hex(b"DEMO") not in text                    # no photo titles
    for j in jpegs:                                     # no 8-byte run of any image
        for k in range(0, len(j) - 8, 97):
            assert _hex(j[k:k + 8]) not in text
    assert "bytes of file data removed" in text
    assert "52 49 4d 47" in text                        # control commands (RIMG) are kept


def test_capture_has_no_photo_data_or_titles_wqv12(tmp_path):
    recs = _records(2)
    text = _capture_text(tmp_path, Wqv12Watch(recs))
    assert _hex(b"PIC0") not in text and _hex(b"PIC1") not in text
    for r in recs:
        for k in range(29, len(r) - 8, 101):
            assert _hex(r[k:k + 8]) not in text
    assert "bytes of photo data removed" in text
    assert "ff b3" in text                              # handshake kept


def test_cli_capture_file(tmp_path):
    from wqvpad.cli import main
    log = tmp_path / "log.txt"
    assert main(["demo", "--model", "3", "--out", str(tmp_path / "out"), "--gap", "0",
                 "--capture", str(log)]) == 0
    text = log.read_text()
    assert text.startswith("# wqvpad") and "Photo data and titles are removed" in text
    assert "ff d8 ff" not in text and _hex(b"DEMO") not in text
