"""Sample photos for `wqvpad demo` and the tests."""

from __future__ import annotations

import base64
import math

from ..images import MONO_RECORD, W, H

_DEMO_JPEGS = [
    (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdB"
    "RkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09P"
    "T09PT09PT09PT09PT0//wAARCACQALADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDlqKKK984gooooAKKKKACiiigAoqWC3muG"
    "2wRO5yAcDgZ9fSr8ehXrrlvLjOejNz+ma562LoUdKk0vma06FWp8EWzLordXw6do3XQDY5AjyP50v/COf9Pf/kP/AOvXH/bW"
    "B/n/AAf+R0f2dif5fxX+Zg0VqvoN6qFlMTkfwqxyfzFUbi0uLY/v4XQZxkjj8+lddHG4es7U5pv1MKmHq09ZRaIKKKK6TEKK"
    "KKACiiigAooooAKKKKACiiigAooq1YWUt9P5cfCjlnPRRUVKkKUHObskVCEpyUYq7ZDDDLcSCOGNnY9gK6Cx0OKIB7vEsmfu"
    "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"
    ),
    (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdB"
    "RkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09P"
    "T09PT09PT09PT09PT0//wAARCACQALADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDtqKKK+TOoKKKKACiiigAooooAKKjnuIbd"
    "d00qIMEjJ5OPT1qhJrtkjYXzJBjqq8frirjSnP4UZTrU4fE7GnRWG3iIbjttSVzwS+D/ACpP+Ei/6dP/ACJ/9atfqlbt+Rj9"
    "eofzfgzdorLTXrNnCsJUB/iZRgfkavW93b3I/cTI5xnAPP5dazlSnH4kbQr056RkiaiiiszUKKKKACiiigAooooAKKKKACii"
    "igAooqtfXsVlB5knLHhUHVjTjFydkTKSiuaWxNNNFBGZJnVFHcmufvtcllJS1zFHj7xHzH/CqF3eT3kged84+6BwF+lLZ2Nx"
    "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"
    )
]


def casio_jpeg(jfif: bytes, title: str, stamp: tuple[int, int, int, int, int]) -> bytes:
    """Insert Casio's APP2 metadata (title + year-2000, month, day, hour, minute) after APP0."""
    assert jfif[:4] == b"\xff\xd8\xff\xe0"
    app0_len = (jfif[4] << 8) | jfif[5]
    cut = 4 + app0_len
    payload = title.encode("ascii").ljust(24, b" ") + bytes(stamp)
    app2 = b"\xff\xe2" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jfif[:cut] + app2 + jfif[cut:]


def demo_jpegs() -> list[bytes]:
    out = []
    for i, b in enumerate(_DEMO_JPEGS):
        out.append(casio_jpeg(base64.b64decode(b), f"DEMO {i + 1}", (1, 7, 14 + i, 9, 30 + i)))
    return out


def mono_record(title: str, stamp: tuple[int, int, int, int, int], seed: int) -> bytes:
    """A WQV-1/2 photo record with a test pattern."""
    px = bytearray(W * H // 2)
    for i in range(W * H):
        x, y = i % W, i // W
        v = int(7.5 + 7.5 * math.sin((x + seed * 13) / 9.0) * math.cos(y / 11.0)) & 0xF
        if i % 2 == 0:
            px[i // 2] |= v
        else:
            px[i // 2] |= v << 4
    rec = title.encode("ascii").ljust(24, b" ") + bytes(stamp) + bytes(px)
    assert len(rec) == MONO_RECORD
    return rec


def sample_watch(model: int):
    if model in (1, 2):
        from .wqv12_watch import Wqv12Watch
        w = Wqv12Watch([mono_record(f"DEMO {k + 1}", (1, 3, 2 + k, 12, 5 * k), k) for k in range(3)])
    else:
        from .wqv310_watch import Wqv310Watch
        w = Wqv310Watch(model, demo_jpegs())
    w.sim_model = model
    return w
