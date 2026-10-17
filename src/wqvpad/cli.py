"""wqvpad command line."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__
from .core import SERIAL_ADAPTERS, Options, NoWatch, download
from .transport.base import TransportError

ADAPTER_HELP = ("pad1, pad2, pad2b (Casio serial pods via a COM port), serial (any other serial IrDA pod) "
                "or pad5 (USB; on Windows wqvpad offers to install its driver)")


def _open_transport(args):
    a = args.adapter.lower().replace("-", "")
    if a in SERIAL_ADAPTERS:
        if not args.port:
            sys.exit("--port is required for serial adapters (for example --port COM3). Run 'wqvpad list'.")
        from .transport.serial_pod import SerialPod
        if a == "pad1" and args.baud != 115200:
            sys.exit("The PAD-1 is only reset to 115200 by wqvpad; other speeds are not supported for it.")
        return SerialPod(args.port, baud=args.baud, dtr=not args.no_dtr, rts=not args.no_rts,
                         litelink_reset=(a == "pad1"))
    if a == "pad5":
        from .transport.stir4200 import Pad5
        return Pad5(baud=args.baud, tx_power=args.tx_power, rx_sensitivity=args.rx_sensitivity,
                    rx_slow=args.rx_slow, index=args.index)
    sys.exit(f"Unknown adapter {args.adapter!r}. Use {ADAPTER_HELP}.")


class Capture:
    """Writes a privacy-safe log of the conversation with the watch for troubleshooting.

    Only protocol control bytes are kept; photo data and photo titles are
    removed before anything is written (see redact.py).
    """

    def __init__(self, path: Path, args) -> None:
        import platform
        self.f = open(path, "w", encoding="utf-8")
        self.t0 = time.monotonic()
        self.f.write(f"# wqvpad {__version__} capture. Photo data and titles are removed.\n")
        self.f.write(f"# system: {platform.system()} {platform.release()}, Python {platform.python_version()}\n")
        adapter = getattr(args, "adapter", "demo")
        self.f.write(f"# adapter: {adapter}, model: {args.model}, gap: {args.gap} ms\n")
        self.f.write("# columns: <ms> <tx|rx> <address> <control> len=<data length> <data>\n")

    def __call__(self, direction: str, text: str) -> None:
        self.f.write(f"{(time.monotonic() - self.t0) * 1000:10.1f} {direction} {text}\n")
        self.f.flush()


class Progress:
    def __init__(self) -> None:
        self.last = ""

    def __call__(self, stage: str, done: int, total: int) -> None:
        if total:
            msg = f"\r  {stage}: {done * 100 // total:3d}%"
        else:
            msg = f"\r  {stage}: {done:,} bytes"
        if msg != self.last:
            sys.stderr.write(msg + " " * 8)
            sys.stderr.flush()
            self.last = msg

    def end(self) -> None:
        if self.last:
            sys.stderr.write("\n")
            self.last = ""


def cmd_list(args) -> int:
    from .transport.serial_pod import list_serial_ports
    from .transport.stir4200 import find_pad5_devices
    ports = list_serial_ports()
    print("Serial ports (PAD-1, PAD-2, PAD-2B through a USB-serial adapter):")
    for dev, desc in ports or []:
        print(f"  {dev:10s} {desc}")
    if not ports:
        print("  none found")
    pads = find_pad5_devices()
    print("PAD-5 USB adapters (066F:4200):")
    if pads:
        for i, d in enumerate(pads):
            print(f"  #{i} bus {getattr(d, 'bus', '?')} address {getattr(d, 'address', '?')}")
    else:
        print("  none found (or the WinUSB driver / libusb is not installed)")
    return 0


def cmd_pad5_info(args) -> int:
    from .transport.stir4200 import Pad5
    with Pad5(index=args.index) as pad:
        for k, v in pad.info().items():
            print(f"{k:14s} {v}")
    return 0


def _run_download(transport, args) -> int:
    trace = (lambda s: print("   " + s, file=sys.stderr)) if args.trace else None
    capture = Capture(Path(args.capture), args) if args.capture else None
    progress = Progress()

    def status(msg: str) -> None:
        progress.end()
        print(msg)

    opt = Options(outdir=Path(args.out), model=args.model, wait=args.wait, gap=args.gap / 1000.0,
                  keep_raw=args.keep_raw, trace=trace, capture=capture, status=status,
                  progress=None if args.trace else progress)
    try:
        with transport:
            result = download(transport, opt)
    except NoWatch as e:
        progress.end()
        print(e, file=sys.stderr)
        return 2
    except Exception as e:  # protocol or transport failure: report clearly
        progress.end()
        print(f"Transfer failed: {e}", file=sys.stderr)
        if not args.capture:
            print("Tip: run again with --capture log.txt and share the file when reporting a problem.",
                  file=sys.stderr)
        return 1
    progress.end()
    print(f"Done: {len(result.saved)} photo(s) saved to {Path(args.out).resolve()}")
    return 0


def cmd_download(args) -> int:
    try:
        transport = _open_transport(args)
    except TransportError as e:
        print(e, file=sys.stderr)
        is_pad5 = args.adapter.lower().replace("-", "") == "pad5"
        if not (is_pad5 and os.name == "nt"):
            return 1
        # All-in-one: the usual cause on Windows is the missing WinUSB driver
        print("\nThe PAD-5 needs a one-time driver setup on Windows.")
        from .driver import ask_yes, install_pad5_driver
        if not install_pad5_driver(ask=None if args.yes else ask_yes):
            return 1
        try:
            transport = _open_transport(args)
        except TransportError as e2:
            print(e2, file=sys.stderr)
            print("If the PAD-5 is plugged in, unplug it, plug it back in and try again.", file=sys.stderr)
            return 1
    return _run_download(transport, args)


def cmd_install_driver(args) -> int:
    from .driver import ask_yes, install_pad5_driver
    return 0 if install_pad5_driver(ask=None if args.yes else ask_yes) else 1


def cmd_demo(args) -> int:
    """Download from a simulated watch, to check the install and see the output."""
    from .sim import SimTransport
    from .sim.samples import sample_watch
    watch = sample_watch(int(args.model))
    args.model = "auto"
    print(f"Simulated WQV-{watch.sim_model} (no hardware involved)")
    return _run_download(SimTransport(watch), args)


def cmd_convert(args) -> int:
    from .images import PhotoWriter, split_mono_dump
    data = Path(args.dump).read_bytes()
    w = PhotoWriter(Path(args.out))
    for p in split_mono_dump(data):
        w.save_mono(p)
    print(f"{len(w.saved)} photo(s) written to {Path(args.out).resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wqvpad", description="Download photos from Casio WQV wrist cameras "
                                "through Casio PAD infrared adapters on modern Windows, macOS and Linux.")
    p.add_argument("--version", action="version", version=f"wqvpad {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list COM ports and PAD-5 adapters").set_defaults(func=cmd_list)

    dr = sub.add_parser("install-driver", help="Windows: set up the PAD-5 driver (asks for admin permission once)")
    dr.add_argument("--yes", action="store_true", help="don't ask for confirmation first")
    dr.set_defaults(func=cmd_install_driver)

    i = sub.add_parser("pad5-info", help="read the PAD-5 chip registers (hardware check)")
    i.add_argument("--index", type=int, default=0)
    i.set_defaults(func=cmd_pad5_info)

    def common(sp):
        sp.add_argument("--out", default="wqv_photos", help="output folder (default: wqv_photos)")
        sp.add_argument("--wait", type=float, default=60, help="seconds to wait for the watch (default 60)")
        sp.add_argument("--gap", type=float, default=10, help="pause in ms before each reply (default 10)")
        sp.add_argument("--keep-raw", action="store_true", help="also save the raw data from the watch")
        sp.add_argument("--trace", action="store_true", help="print every frame")
        sp.add_argument("--capture", metavar="FILE", help="save a privacy-safe log of the conversation to FILE, for bug reports")

    d = sub.add_parser("download", help="download photos from a watch")
    d.add_argument("--adapter", required=True, help=ADAPTER_HELP)
    d.add_argument("--port", help="COM port for serial adapters, e.g. COM3 or /dev/ttyUSB0")
    d.add_argument("--model", default="auto", choices=["auto", "1", "2", "3", "10"],
                   help="watch model (default: detect)")
    d.add_argument("--baud", type=int, default=115200, help="IR speed (default 115200, used by all WQV models)")
    d.add_argument("--no-dtr", action="store_true", help="serial: hold DTR low (default high)")
    d.add_argument("--no-rts", action="store_true", help="serial: hold RTS low (default high)")
    d.add_argument("--index", type=int, default=0, help="PAD-5: which adapter if several are plugged in")
    d.add_argument("--tx-power", type=int, default=0, help="PAD-5: 0 (strongest) to 3")
    d.add_argument("--rx-sensitivity", type=int, default=1, help="PAD-5: 0 (most sensitive) to 6")
    d.add_argument("--rx-slow", action="store_true", help="PAD-5: use the slow receive line (try if nothing is heard)")
    d.add_argument("--yes", action="store_true", help="PAD-5 on Windows: install the driver without asking first")
    common(d)
    d.set_defaults(func=cmd_download)

    m = sub.add_parser("demo", help="download from a simulated watch (no hardware needed)")
    m.add_argument("--model", default="10", choices=["1", "2", "3", "10"])
    common(m)
    m.set_defaults(func=cmd_demo)

    c = sub.add_parser("convert", help="convert a saved WQV-1/2 raw dump (--keep-raw) to PNG")
    c.add_argument("dump")
    c.add_argument("--out", default="wqv_photos")
    c.set_defaults(func=cmd_convert)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
