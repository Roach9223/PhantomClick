"""Disk-backed cache for RS Wiki responses.

Lives at ``debug/wiki_cache/<sha1>.json`` — one file per unique
``(endpoint, params)`` tuple. Keeps the cache out of user-visible
paths (just another debug artifact). 24 h TTL is enough for almost
everything the wiki hosts; nothing in this cache is load-bearing so
TTL-stale returns are fine when the network drops.

Entry schema::

    {"fetched_at": <unix>,
     "key": "<endpoint>|<sorted-params>",
     "value": <response dict>}
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_TTL_S = 24 * 60 * 60


class WikiCache:
    """Disk-backed k/v cache with TTL + stale fallback."""

    def __init__(self, root: Path, ttl_s: float = DEFAULT_TTL_S) -> None:
        self._root = Path(root)
        self._ttl_s = float(ttl_s)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """Filesystem root holding the cache files. Read-only."""
        return self._root

    @staticmethod
    def _key(endpoint: str, params: Dict[str, Any]) -> str:
        """Stable hash of endpoint + sorted params."""
        payload = endpoint + "|" + json.dumps(
            sorted(params.items()), separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _path_for(self, endpoint: str, params: Dict[str, Any]) -> Path:
        return self._root / (self._key(endpoint, params) + ".json")

    def get(
        self, endpoint: str, params: Dict[str, Any], *, allow_stale: bool = False
    ) -> Tuple[Optional[Any], bool]:
        """Return ``(value, is_stale)``. ``value`` is None on miss."""
        path = self._path_for(endpoint, params)
        if not path.exists():
            return None, False
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None, False
        age = time.time() - float(entry.get("fetched_at", 0))
        if age <= self._ttl_s:
            return entry.get("value"), False
        if allow_stale:
            return entry.get("value"), True
        return None, False

    def set(self, endpoint: str, params: Dict[str, Any], value: Any) -> None:
        path = self._path_for(endpoint, params)
        entry = {
            "fetched_at": time.time(),
            "key": f"{endpoint}|{sorted(params.items())}",
            "value": value,
        }
        try:
            path.write_text(
                json.dumps(entry, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            # Cache is best-effort; a write failure shouldn't break the caller.
            pass

    def clear(self) -> int:
        """Delete every cache file. Returns count removed. Safe to call live."""
        n = 0
        for p in self._root.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
        return n
