"""One-step PAD-5 driver setup on Windows.

The PAD-5 needs Microsoft's generic WinUSB driver so wqvpad can talk to it.
Instead of asking people to run Zadig, we run libwdi's small `wdi-simple`
tool (LGPL v3, by Pete Batard, the author of Zadig), which installs WinUSB
for exactly one device: USB ID 066F:4200.

The Windows build of wqvpad bundles wdi-simple.exe. Installing any driver
needs administrator rights, so Windows shows one permission prompt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .transport.stir4200 import PID, VID

EXE_NAME = "wdi-simple.exe"

WHY_ADMIN = """\
Windows will now ask for permission ("Do you want to allow this app to make
changes to your device?"). This is needed once, because installing any
driver requires administrator rights. What it installs:

  * Microsoft's own WinUSB driver (part of Windows), set up only for the
    Casio PAD-5 (USB ID 066F:4200). No other device is touched.
  * A small certificate, created on your PC, that lets Windows accept this
    one driver setup file. This is how Zadig does it too.

Nothing is downloaded and nothing runs in the background afterwards.
You can undo it in Device Manager: right-click the PAD-5, choose
"Uninstall device" and tick "Delete the driver software".
"""

# libwdi result codes (libwdi.h)
WDI_ERRORS = {
    -1: "input/output error", -2: "invalid parameter", -3: "access denied",
    -4: "device not found", -5: "not found", -6: "busy (another driver install is running)",
    -7: "timed out", -9: "another installation is pending, restart Windows and try again",
    -14: "cancelled (the permission prompt was declined)",
    -15: "administrator rights are required", -16: "32-bit installer on 64-bit Windows",
    -19: "driver is unsigned",
}


def is_windows() -> bool:
    return os.name == "nt"


def find_installer() -> Optional[Path]:
    """Look for wdi-simple.exe: inside the bundled .exe, next to the package, or on PATH."""
    candidates = []
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller one-file bundle
    if base:
        candidates.append(Path(base) / "wqvpad" / "bin" / EXE_NAME)
    candidates.append(Path(__file__).resolve().parent / "bin" / EXE_NAME)
    candidates.append(Path(sys.executable).resolve().parent / EXE_NAME)
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which(EXE_NAME)
    return Path(found) if found else None


def installer_command(exe: Path, dest: Path) -> list[str]:
    return [
        str(exe),
        "--name", "CASIO PAD-5",
        "--manufacturer", "Casio",
        "--vid", f"0x{VID:04X}",
        "--pid", f"0x{PID:04X}",
        "--type", "0",                 # 0 = WinUSB
        "--inf", "casio_pad5.inf",
        "--dest", str(dest),
    ]


def install_pad5_driver(say: Callable[[str], None] = print, ask: Optional[Callable[[str], bool]] = None,
                        installer: Optional[Path] = None) -> bool:
    """Install WinUSB for the PAD-5. Returns True on success."""
    if not is_windows():
        say("The driver step is only needed on Windows. On Linux and macOS the PAD-5 works through libusb as is.")
        return True
    exe = installer or find_installer()
    if exe is None:
        say("The driver installer (wdi-simple.exe) is not included in this copy of wqvpad.\n"
            "Use wqvpad.exe from the Releases page, which includes it, or install WinUSB for\n"
            "USB ID 066F:4200 with Zadig (see the README).")
        return False
    say(WHY_ADMIN)
    if ask is not None and not ask("Install the PAD-5 driver now? [Y/n] "):
        say("Skipped. You can run 'wqvpad install-driver' any time.")
        return False
    dest = Path(tempfile.gettempdir()) / "wqvpad_pad5_driver"
    say("Installing... (this can take a minute)")
    proc = subprocess.run(installer_command(exe, dest), capture_output=True, text=True)
    code = proc.returncode
    if code > 0x7FFFFFFF:  # Windows reports negative exit codes as large unsigned values
        code -= 1 << 32
    if code == 0:
        say("PAD-5 driver installed.")
        return True
    detail = WDI_ERRORS.get(code, f"error {code}")
    say(f"Driver install failed: {detail}.")
    if proc.stdout.strip():
        say(proc.stdout.strip())
    return False


def ask_yes(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("", "y", "yes")
