"""Simulated adapters and watches for testing without hardware.

The simulated watches replay the conversations recorded from real watches
(Groeber's WQV-1 notes and the frame traces in wqv-blink). They check that
our side says the right things in the right order, but they are only as
accurate as those recordings: a real watch is the final test.
"""

from __future__ import annotations

import collections
from typing import Deque, Iterable

from ..frame import Check, Frame, decode
from ..transport.base import Transport


class SimWatch:
    check: Check = Check.SUM16

    def on_frame(self, f: Frame) -> Iterable[bytes]:  # pragma: no cover - interface
        raise NotImplementedError


class SimTransport(Transport):
    """In-memory adapter wired to a simulated watch."""

    name = "sim"

    def __init__(self, watch: SimWatch, echo: bool = False, noise: bytes = b"") -> None:
        super().__init__(suppress_echo=True)
        self.watch = watch
        self.echo = echo
        self.noise = noise
        self._rx: Deque[bytes] = collections.deque()
        self.tx_log: list[bytes] = []

    def _write_raw(self, data: bytes) -> None:
        self.tx_log.append(data)
        if self.echo:
            self._rx.append(data)
        f = decode(data, self.watch.check)
        if not f.ok:
            return
        for wire in self.watch.on_frame(f) or ():
            self._rx.append(self.noise + wire)

    def _read_some(self, timeout: float) -> bytes:
        if self._rx:
            return self._rx.popleft()
        # Nothing will ever arrive in a synchronous simulation; don't really sleep long
        import time
        time.sleep(min(timeout, 0.001))
        return b""
