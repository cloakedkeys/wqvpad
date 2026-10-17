"""Casio PAD-5: USB infrared adapter built on the SigmaTel STIr4200 chip.

Casio's PAD-5 driver is a 32-bit NDIS 5 kernel driver for Windows 98-XP and
cannot load on Windows 11. Instead, this module talks to the chip directly
from user space through libusb:

1. Once, bind the PAD-5 (USB ID 066F:4200) to the WinUSB driver with Zadig.
2. This code then programs the chip's registers itself and streams bytes.

In SIR mode (115200 baud and below) the chip only modulates and demodulates
light: the host builds and checks every frame. That is exactly what we need,
because the WQV-1/2 use a non-standard checksum that a real IrDA stack would
reject.

Register facts below were taken from the SigmaTel datasheet as documented in
the (GPL) Linux stir4200 driver; this file is an independent implementation.
"""

from __future__ import annotations

import time
from typing import Optional

from .base import Transport, TransportError

VID, PID = 0x066F, 0x4200
EP_OUT, EP_IN = 0x01, 0x82
FIFO_SIZE = 4096

# Vendor requests
REQ_WRITE_REG = 0x00
REQ_READ_REG = 0x01
REQ_READ_ROM = 0x02
REQ_WRITE_SINGLE = 0x03

# Registers
REG_MODE = 1
REG_PDCLK = 2
REG_CTRL1 = 3
REG_CTRL2 = 4
REG_FIFOCTL = 5
REG_FIFOLSB = 6
REG_FIFOMSB = 7
REG_DPLL = 8
REG_IRDIG = 9
REG_TEST = 15

# MODE bits
MODE_FIR = 0x80
MODE_SIR = 0x20
MODE_ASK = 0x10
MODE_FASTRX = 0x08
MODE_FFRSTEN = 0x04
MODE_NRESET = 0x02
MODE_2400 = 0x01

# CTRL1 bits
CTRL1_SDMODE = 0x80
CTRL1_RXSLOW = 0x40
CTRL1_TXPWD = 0x10
CTRL1_RXPWD = 0x08
CTRL1_SRESET = 0x01

# FIFOCTL bits
FIFOCTL_DIR = 0x10  # set while the FIFO is transmitting
FIFOCTL_CLR = 0x08
FIFOCTL_EMPTY = 0x04

PDCLK = {2400: 0xDF, 9600: 0x77, 19200: 0x3B, 38400: 0x1D, 57600: 0x13, 115200: 0x09}


def _backend():
    """Find a libusb backend, preferring the bundled DLL from libusb-package on Windows."""
    try:
        import libusb_package  # type: ignore

        return libusb_package.get_libusb1_backend()
    except Exception:
        return None


def find_pad5_devices():
    try:
        import usb.core
    except ImportError:  # pragma: no cover
        return []
    try:
        return list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=_backend()) or [])
    except Exception:
        return []


class Pad5(Transport):
    name = "pad5"

    def __init__(self, baud: int = 115200, tx_power: int = 0, rx_sensitivity: int = 1,
                 rx_slow: bool = False, index: int = 0, suppress_echo: bool = True) -> None:
        super().__init__(suppress_echo=suppress_echo)
        if baud not in PDCLK:
            raise TransportError(f"PAD-5 does not support {baud} baud in SIR mode")
        try:
            import usb.core
            import usb.util
        except ImportError as e:  # pragma: no cover
            raise TransportError("pyusb is not installed (pip install pyusb libusb-package)") from e
        self._usb = usb
        devs = find_pad5_devices()
        if not devs:
            raise TransportError(
                "No PAD-5 found (USB 066F:4200). Is it plugged in, and bound to WinUSB with Zadig?")
        if index >= len(devs):
            raise TransportError(f"Only {len(devs)} PAD-5 adapter(s) found")
        self.dev = devs[index]
        try:
            try:
                self.dev.set_configuration()
            except usb.core.USBError:
                pass  # already configured
            usb.util.claim_interface(self.dev, 0)
            for ep in (EP_OUT, EP_IN):
                try:
                    self.dev.clear_halt(ep)
                except usb.core.USBError:
                    pass
        except usb.core.USBError as e:
            raise TransportError(
                f"Could not open the PAD-5 ({e}). On Windows, install the WinUSB driver for it with Zadig.") from e
        self.baud = baud
        self.tx_power = tx_power & 3
        self.rx_sensitivity = rx_sensitivity & 7
        self.rx_slow = rx_slow
        self.set_speed(baud)

    # --- registers -------------------------------------------------------
    def write_reg(self, reg: int, value: int) -> None:
        self.dev.ctrl_transfer(0x40, REQ_WRITE_SINGLE, value & 0xFF, reg, None, 100)

    def read_regs(self, reg: int, count: int) -> bytes:
        return bytes(self.dev.ctrl_transfer(0xC0, REQ_READ_REG, 0, reg, count, 100))

    def set_speed(self, baud: int) -> None:
        # Note: writing several registers in one request does not work on this chip.
        self.write_reg(REG_CTRL1, CTRL1_SRESET)       # reset the modulator
        self.write_reg(REG_DPLL, 0x15)                # DPLL tuning value used by every known driver
        self.write_reg(REG_PDCLK, PDCLK[baud])        # bit clock
        mode = MODE_NRESET | MODE_FASTRX | MODE_SIR
        if baud == 2400:
            mode |= MODE_2400
        self.write_reg(REG_MODE, mode)
        ctrl1 = (self.tx_power << 1) | (CTRL1_RXSLOW if self.rx_slow else 0)
        self.write_reg(REG_CTRL1, CTRL1_SDMODE | ctrl1)  # pulses SD to reset TEMIC-style transceivers
        self.write_reg(REG_CTRL1, ctrl1)
        self.write_reg(REG_CTRL2, self.rx_sensitivity << 5)
        self.baud = baud

    def fifo_status(self) -> tuple[int, int]:
        r = self.read_regs(REG_FIFOCTL, 3)
        return r[0], ((r[2] & 0x1F) << 8) | r[1]

    def wait_tx_done(self, timeout: float = 2.0) -> None:
        """Wait until the chip has finished sending. Reading while it is still
        transmitting confuses it."""
        deadline = time.monotonic() + timeout
        prev = None
        while time.monotonic() < deadline:
            status, count = self.fifo_status()
            if not (status & FIFOCTL_DIR) or (status & FIFOCTL_EMPTY):
                return
            if prev is not None and count > prev:
                break  # FIFO confused: count went up while draining
            prev = count
            time.sleep(max(0.001, count * 10 / self.baud))
        self.write_reg(REG_FIFOCTL, FIFOCTL_CLR)
        self.write_reg(REG_FIFOCTL, 0)

    def info(self) -> dict:
        regs = self.read_regs(0, 10)
        return {
            "usb": f"{VID:04x}:{PID:04x}",
            "bus": getattr(self.dev, "bus", None),
            "address": getattr(self.dev, "address", None),
            "registers": regs.hex(" "),
            "chip_revision": regs[REG_CTRL2] & 0x03,
            "mode": f"{regs[REG_MODE]:02x}",
            "pdclk": f"{regs[REG_PDCLK]:02x}",
        }

    # --- Transport hooks ------------------------------------------------
    def _write_raw(self, data: bytes) -> None:
        if len(data) > FIFO_SIZE - 4:
            raise TransportError("frame too large for the PAD-5 FIFO")
        n = len(data)
        packet = bytes((0x55, 0xAA, n & 0xFF, (n >> 8) & 0xFF)) + data
        self.dev.write(EP_OUT, packet, 1000)
        self.wait_tx_done()

    def _read_some(self, timeout: float) -> bytes:
        try:
            return bytes(self.dev.read(EP_IN, FIFO_SIZE, max(1, int(timeout * 1000))))
        except self._usb.core.USBTimeoutError:
            return b""
        except self._usb.core.USBError as e:
            if getattr(e, "errno", None) in (110, 10060) or "timeout" in str(e).lower():
                return b""
            raise TransportError(f"PAD-5 read failed: {e}") from e

    def close(self) -> None:
        try:
            self.write_reg(REG_CTRL1, CTRL1_TXPWD | CTRL1_RXPWD)  # power down the transceiver
        except Exception:
            pass
        try:
            self._usb.util.release_interface(self.dev, 0)
            self._usb.util.dispose_resources(self.dev)
        except Exception:
            pass
