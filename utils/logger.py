"""File logger for PhantomClick. Rotates at 5MB, no console output.

5 MB × 2 backup files = 15 MB on-disk budget. With per-click +
per-event diagnostic lines (~150 bytes each), that holds ~30k click
events per file × 3 files ≈ 90k clicks of history. Enough that a
user reporting "missed clicks at 4 hours in" still has the whole
session's log when they share it.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _log_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "phantomclick.log"


def log_path() -> Path:
    """Public accessor for the active log file path."""
    return _log_path()


def get_logger(name: str = "phantomclick") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(_log_path(), maxBytes=5_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def clear_log(name: str = "phantomclick") -> bool:
    """Truncate the active log file (and remove any rotated backups) so
    a fresh debugging session starts from byte zero. Subsequent log
    calls re-open the file and write into the now-empty path.

    The handlers must be closed first or Windows holds an exclusive lock
    on the file. After truncation we re-acquire via ``get_logger()`` so
    the next emit doesn't crash on a missing handler. Returns True on
    success, False if the file couldn't be truncated (most often: the
    file is held by another process — rare since we own the only open
    handle here)."""
    logger = logging.getLogger(name)
    p = _log_path()
    # Drop existing handlers so the file lock releases before truncate.
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)
    try:
        with open(p, "w", encoding="utf-8") as f:
            pass
    except Exception:
        # Re-attach a handler so the app keeps logging even after a
        # failed clear; the user can investigate from the partial file.
        get_logger(name)
        return False
    # Sweep rotated backups (.log.1, .log.2, ...). Any failure here is
    # cosmetic — the live log file is what matters.
    for sib in p.parent.glob(p.name + ".*"):
        try:
            sib.unlink()
        except Exception:
            pass
    # Re-attach the handler so the next log call writes into the fresh
    # file. ``get_logger`` is idempotent: it adds a handler only when
    # ``logger.handlers`` is empty, which we just made it.
    get_logger(name)
    return True
