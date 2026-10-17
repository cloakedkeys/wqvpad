"""Transport interface: moves raw bytes between the PC and an infrared adapter."""

from __future__ import annotations

import time
from typing import Optional

EOF = 0xC1


class TransportError(Exception):
    pass


class Transport:
    """Byte pipe to an IR adapter.

    Subclasses implement `_write_raw` and `_read_some`. The base class handles
    splitting the incoming byte stream into frames (everything up to an EOF
    byte) and drops our own transmissions if the adapter echoes them back,
    which some IR transceivers do because they can see their own light.
    """

    name = "transport"

    def __init__(self, suppress_echo: bool = True) -> None:
        self._buf = bytearray()
        self._last_tx: Optional[bytes] = None
        self.suppress_echo = suppress_echo

    # --- subclass hooks -------------------------------------------------
    def _write_raw(self, data: bytes) -> None:
        raise NotImplementedError

    def _read_some(self, timeout: float) -> bytes:
        """Return whatever bytes arrive within `timeout` seconds (may be empty)."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    # --- public API ------------------------------------------------------
    def write(self, data: bytes) -> None:
        self._last_tx = bytes(data)
        self._write_raw(bytes(data))

    def reset_input(self) -> None:
        self._buf.clear()

    def read_until_eof(self, timeout: float) -> bytes:
        """Return bytes up to and including the next EOF (C1h).

        On timeout, returns whatever partial data arrived (possibly empty).
        """
        deadline = time.monotonic() + timeout
        while True:
            idx = self._buf.find(bytes((EOF,)))
            if idx >= 0:
                chunk = bytes(self._buf[: idx + 1])
                del self._buf[: idx + 1]
                if self._is_echo(chunk):
                    continue
                return chunk
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                partial = bytes(self._buf)
                self._buf.clear()
                return partial
            self._buf += self._read_some(min(remaining, 0.05))

    def _is_echo(self, chunk: bytes) -> bool:
        if not (self.suppress_echo and self._last_tx):
            return False
        # Compare the frame bodies, ignoring how many BOF / padding bytes surround them
        def body(b: bytes) -> bytes:
            return b.lstrip(b"\xff").lstrip(b"\xc0")
        if body(chunk) == body(self._last_tx):
            self._last_tx = None
            return True
        return False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
