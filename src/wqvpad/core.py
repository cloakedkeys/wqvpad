"""High-level download: open an adapter, find the watch, save the photos."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import wqv12, wqv310
from .frame import Link
from .images import PhotoWriter
from .transport.base import Transport

SERIAL_ADAPTERS = {"pad1", "pad2", "pad2b", "serial"}
USB_ADAPTERS = {"pad5"}
FAMILY = {"1": "12", "2": "12", "3": "310", "10": "310", "auto": "auto"}


@dataclass
class Options:
    outdir: Path = Path("wqv_photos")
    model: str = "auto"
    wait: float = 60.0
    gap: float = 0.01
    timeout: float = 1.0
    keep_raw: bool = False
    trace: Optional[Callable[[str], None]] = None
    capture: Optional[Callable[[str, str], None]] = None
    status: Callable[[str], None] = print
    progress: Optional[Callable[[str, int, int], None]] = None


@dataclass
class Result:
    model: int = 0
    saved: list[Path] = field(default_factory=list)


class NoWatch(Exception):
    pass


def download(transport: Transport, opt: Options) -> Result:
    family = FAMILY[opt.model]
    l12 = Link(transport, wqv12.CHECK, gap=opt.gap, default_timeout=opt.timeout, trace=opt.trace,
               capture=opt.capture)
    l310 = Link(transport, wqv310.CHECK, gap=opt.gap, default_timeout=opt.timeout, trace=opt.trace,
                capture=opt.capture)
    writer = PhotoWriter(opt.outdir)
    progress = opt.progress or (lambda *_: None)

    opt.status("Waiting for the watch. On the watch: IR Mode > Communication Menu > PC > press F\n"
               "(it shows REMOTE), then point it at the adapter from 5-10 cm away.")
    deadline = time.monotonic() + opt.wait
    while time.monotonic() < deadline:
        if family in ("12", "auto"):
            s12 = wqv12.Wqv12Session(l12, progress=progress)
            if s12.open_session():
                opt.status("Connected to a WQV-1/WQV-2. Downloading...")
                photos, dump = s12.run()
                if opt.keep_raw:
                    writer.save_raw("wqv12_dump.bin", dump)
                for p in photos:
                    writer.save_mono(p)
                return Result(model=12, saved=list(writer.saved))
        if family in ("310", "auto"):
            def on_file(name: str, data: bytes, model: int) -> None:
                if opt.keep_raw:
                    writer.save_raw(f"raw_{len(writer.saved) + 1:02d}_{name or 'photo'}.bin", data)
                path = writer.save_jpeg(data, model)
                opt.status(f"  saved {path.name}")

            s310 = wqv310.Wqv310Session(l310, progress=progress, on_file=on_file)
            if s310.open_session():
                opt.status(f"Connected to a WQV-{s310.model}. Downloading...")
                s310.run()
                return Result(model=s310.model, saved=list(writer.saved))
        transport.reset_input()
    raise NoWatch("No watch answered. Check that it is in IR transfer mode and pointed at the adapter (5-10 cm).")
