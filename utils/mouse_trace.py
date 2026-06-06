"""Cursor-movement trace for diagnosing weird movement.

Off by default — enable from the Settings card's Diagnostics section.
Once on, every cursor write (``dpi_cursor.set_pos``) and every cursor
read (``dpi_cursor.get_pos``) is logged with a monotonic timestamp,
plus bracketing markers emitted by the humanizer / engine so each batch
of writes is attributable to the operation that drove it.

The output format is JSONL — one JSON object per line — for two reasons:

* Easy to grep / tail / open in a text editor.
* Parseable by pandas / jq / Python without a custom decoder.

Each record has a short ``k`` (kind) field so the file is dense; full
field meanings are documented next to the emitter call sites in
:mod:`utils.dpi_cursor`, :mod:`utils.humanizer`, and
:mod:`modules.clicker`.

Thread safety: a single :class:`threading.Lock` serialises writes. The
engine fires ~50–200 events/sec at high realism, well under the
contention threshold.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional, TextIO

# Rotation budget. The trace is debug-only so we don't need a deep
# archive — one rotation is plenty for "roll back and look at what just
# happened." Kept small so a 10-hour session doesn't fill the install
# directory: at ~150 events/sec × ~150 bytes/event = ~80 MB/hour, so
# the 10 MB cap rolls every ~7 minutes when the trace is on. The size
# check itself runs every _SIZE_CHECK_EVERY events so it's not a
# per-event syscall on the hot path.
_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
_SIZE_CHECK_EVERY: int = 1000

_lock = threading.Lock()
_file: Optional[TextIO] = None
_t0: float = 0.0
_event_count: int = 0
_path: Optional[str] = None
_bytes_written: int = 0


def enable(path: str) -> bool:
    """Begin tracing to ``path``. No-op if already enabled.

    Returns True on success, False if a trace was already running.
    """
    global _file, _t0, _event_count, _path, _bytes_written
    with _lock:
        if _file is not None:
            return False
        try:
            f = open(path, "w", encoding="utf-8", buffering=1)
        except OSError:
            return False
        _file = f
        _t0 = time.monotonic()
        _event_count = 0
        _bytes_written = 0
        _path = path
        f.write(json.dumps({
            "k": "trace_start",
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }) + "\n")
        return True


def _rotate_locked() -> None:
    """Move the current file aside to ``<path>.1`` and reopen ``<path>``
    fresh. Caller must hold ``_lock``. Single-backup rotation; the prior
    .1 (if any) is overwritten because deeper history isn't useful for
    debugging the most recent run.
    """
    global _file, _bytes_written
    f = _file
    path = _path
    if f is None or path is None:
        return
    try:
        f.close()
    except OSError:
        pass
    _file = None
    backup = path + ".1"
    try:
        if os.path.exists(backup):
            os.remove(backup)
    except OSError:
        pass
    try:
        os.rename(path, backup)
    except OSError:
        # Couldn't rotate — last-ditch: truncate so the file doesn't
        # keep growing past the cap forever.
        try:
            with open(path, "w", encoding="utf-8") as g:
                g.write(json.dumps({"k": "trace_truncate"}) + "\n")
        except OSError:
            return
    try:
        _file = open(path, "w", encoding="utf-8", buffering=1)
        _file.write(json.dumps({
            "k": "trace_rotate",
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }) + "\n")
    except OSError:
        _file = None
    _bytes_written = 0


def disable() -> Optional[str]:
    """Stop tracing. Returns the path that was being written, or None
    if no trace was active."""
    global _file, _path, _event_count
    with _lock:
        f = _file
        path = _path
        events = _event_count
        if f is None:
            return None
        try:
            f.write(json.dumps({"k": "trace_end", "events": events}) + "\n")
            f.close()
        except OSError:
            pass
        _file = None
        _path = None
    return path


def is_enabled() -> bool:
    return _file is not None


def event_count() -> int:
    return _event_count


def event(kind: str, **fields) -> None:
    """Append one record to the trace if enabled.

    The ``is_enabled()`` early-out is checked twice — once outside the
    lock for the common (disabled) fast path, once inside the lock for
    correctness in case ``disable()`` raced with us. Rotates the file
    when it crosses ``_MAX_BYTES`` so a 10-hour session can't fill the
    install directory with a 100+ MB JSONL.
    """
    if _file is None:
        return
    rec = {"t": round(time.monotonic() - _t0, 6), "k": kind}
    if fields:
        rec.update(fields)
    line = json.dumps(rec, separators=(",", ":")) + "\n"
    encoded = line.encode("utf-8")
    with _lock:
        f = _file
        if f is None:
            return
        try:
            f.write(line)
        except OSError:
            return
        global _event_count, _bytes_written
        _event_count += 1
        _bytes_written += len(encoded)
        # Cheap rotation check: only every N events. Even at 200 events/s
        # that's a stat-equivalent every 5 s, well below noise.
        if (_event_count % _SIZE_CHECK_EVERY) == 0 and _bytes_written >= _MAX_BYTES:
            _rotate_locked()
