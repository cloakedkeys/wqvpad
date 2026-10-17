"""Serial infrared pods: Casio PAD-1, PAD-2, PAD-2B, and other serial IrDA pods.

These pods are "dumb": they turn serial bytes into IrDA SIR light pulses and
back, with no protocol knowledge. On Windows 11 they work through any USB-to-
serial adapter (FTDI, Prolific PL2303, CH340...) as an ordinary COM port, so
no special driver is needed.

Power and speed come from the serial control lines:

* The PAD-1 is an OEM Parallax LiteLink pod (HP HSDL-7001 encoder, 3.6864 MHz
  crystal, 74LV174 speed latch; board marked LITELINK). It is powered from
  DTR+RTS, and is reset to its default speed of 115200 by pulsing RTS low
  while DTR stays high. (Each DTR low pulse would then step it down through
  57600, 38400, 19200 and 9600; we never need that.) Weak USB-serial adapters
  may not supply enough power.
* The PAD-2/2B are reportedly rebadged Extended Systems JetEye ESI-9680 pods.
  That pod selects its speed from the lines: DTR+RTS high = 115200,
  DTR only = 19200, RTS only = 9600. So the default (both high) also selects
  115200, the speed every WQV watch uses.
"""

from __future__ import annotations

from .base import Transport, TransportError


class SerialPod(Transport):
    name = "serial"

    def __init__(self, port: str, baud: int = 115200, dtr: bool = True, rts: bool = True,
                 suppress_echo: bool = True, litelink_reset: bool = False) -> None:
        super().__init__(suppress_echo=suppress_echo)
        try:
            import serial  # pyserial
        except ImportError as e:  # pragma: no cover
            raise TransportError("pyserial is not installed (pip install pyserial)") from e
        try:
            # serial_for_url accepts plain names (COM3, /dev/ttyUSB0) and test URLs (loop://)
            self._ser = serial.serial_for_url(port, do_not_open=True)
            self._ser.baudrate = baud
            self._ser.bytesize = serial.EIGHTBITS
            self._ser.parity = serial.PARITY_NONE
            self._ser.stopbits = serial.STOPBITS_ONE
            self._ser.timeout = 0.05
            self._ser.write_timeout = 2
            self._ser.xonxoff = False
            self._ser.rtscts = False
            self._ser.dsrdtr = False
            # Set the lines before opening where the platform allows it, so the
            # pod powers up in the right mode straight away.
            self._ser.dtr = dtr
            self._ser.rts = rts
            self._ser.open()
            self._ser.dtr = dtr
            self._ser.rts = rts
            if litelink_reset:
                self.litelink_reset()
            self._ser.reset_input_buffer()
        except Exception as e:
            raise TransportError(f"Could not open {port}: {e}") from e
        self.port = port

    def litelink_reset(self) -> None:
        """PAD-1 (Parallax LiteLink): power up, then pulse RTS low to reset it to 115200."""
        import time
        self._ser.dtr = True
        self._ser.rts = True
        time.sleep(0.05)   # power settling
        self._ser.rts = False
        time.sleep(0.002)  # datasheet minimum is 15 us
        self._ser.rts = True
        time.sleep(0.01)

    def _write_raw(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def _read_some(self, timeout: float) -> bytes:
        self._ser.timeout = max(0.001, timeout)
        waiting = self._ser.in_waiting
        return self._ser.read(waiting or 1)

    def reset_input(self) -> None:
        super().reset_input()
        self._ser.reset_input_buffer()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:  # pragma: no cover
        return []
    return [(p.device, p.description or "") for p in sorted(list_ports.comports(), key=lambda p: p.device)]
