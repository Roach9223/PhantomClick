"""MediaWiki client for runescape.wiki.

Three public methods. All are cache-first — if the cache has a fresh
entry (≤TTL), it's returned without a network call. Live calls go
through a 1 req/sec token bucket so we stay a good citizen.

The User-Agent header matters — MediaWiki rejects bots with a generic
UA. Ours identifies the tool + its purpose.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .cache import WikiCache


BASE_URL = "https://runescape.wiki/api.php"
USER_AGENT = (
    "rs3vision-studio/0.3 (local-automation-studio; personal-use)"
)
DEFAULT_TIMEOUT_S = 10.0


# ─────────────────────────────────────────────────────────────────
# Rate limiter — simple token bucket
# ─────────────────────────────────────────────────────────────────


class _TokenBucket:
    """Lets at most ``rate`` requests through per second."""

    def __init__(self, rate: float = 1.0) -> None:
        self._interval = 1.0 / max(0.1, rate)
        self._last_fire = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, (self._last_fire + self._interval) - now)
            if wait > 0:
                time.sleep(wait)
            self._last_fire = time.monotonic()


# ─────────────────────────────────────────────────────────────────
# Wiki client
# ─────────────────────────────────────────────────────────────────


class WikiClient:
    def __init__(
        self,
        cache: Optional[WikiCache] = None,
        *,
        user_agent: str = USER_AGENT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        rate_per_sec: float = 1.0,
    ) -> None:
        self._cache = cache
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._timeout = float(timeout_s)
        self._bucket = _TokenBucket(rate_per_sec)

    # ────────────────────────────────────────────────────────────
    # Primitives
    # ────────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Full-text search. Returns ``{results: [{title, snippet, url}]}``."""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": int(max(1, min(50, limit))),
            "utf8": 1,
            "format": "json",
        }
        data = self._get("search", params)
        results = []
        for hit in (data.get("query", {}).get("search") or []):
            title = hit.get("title", "")
            results.append({
                "title": title,
                "snippet": _strip_html(hit.get("snippet", "")),
                "url": f"https://runescape.wiki/w/{title.replace(' ', '_')}",
            })
        return {"query": query, "results": results, "stale": data.get("_stale", False)}

    def page(self, title: str, section: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the rendered text of a wiki page.

        Returns ``{title, url, text, sections, stale}``. ``text`` is
        plain text (wikitext markup + HTML stripped) — LLM-friendly.
        """
        params: Dict[str, Any] = {
            "action": "parse",
            "page": title,
            "prop": "wikitext|sections",
            "format": "json",
            "redirects": 1,
        }
        if section:
            params["section"] = section
        data = self._get("parse", params)
        parse = data.get("parse") or {}
        resolved_title = parse.get("title", title)
        raw_wikitext = (parse.get("wikitext") or {}).get("*", "")
        sections = [
            {"index": s.get("index"), "line": s.get("line"), "level": s.get("level")}
            for s in (parse.get("sections") or [])
        ]
        return {
            "title": resolved_title,
            "url": f"https://runescape.wiki/w/{resolved_title.replace(' ', '_')}",
            "text": _wikitext_to_plain(raw_wikitext),
            "sections": sections,
            "stale": data.get("_stale", False),
        }

    def infobox(self, title: str) -> Dict[str, Any]:
        """Parse the page's first ``{{Infobox}}`` template into a flat dict.

        Returns ``{title, url, infobox_type, fields: {...}, stale}``.
        Empty ``fields`` when no infobox template is found on the page.
        """
        import mwparserfromhell

        params = {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "redirects": 1,
        }
        data = self._get("parse", params)
        parse = data.get("parse") or {}
        resolved_title = parse.get("title", title)
        wikitext = (parse.get("wikitext") or {}).get("*", "")
        if not wikitext:
            return {
                "title": resolved_title,
                "url": f"https://runescape.wiki/w/{resolved_title.replace(' ', '_')}",
                "infobox_type": None,
                "fields": {},
                "stale": data.get("_stale", False),
            }

        parsed = mwparserfromhell.parse(wikitext)
        infobox_type: Optional[str] = None
        fields: Dict[str, Any] = {}
        for tpl in parsed.filter_templates():
            name = str(tpl.name).strip()
            if name.lower().startswith("infobox"):
                infobox_type = name
                for p in tpl.params:
                    key = str(p.name).strip()
                    val = _wikitext_to_plain(str(p.value)).strip()
                    if key and val:
                        fields[key] = val
                break
        return {
            "title": resolved_title,
            "url": f"https://runescape.wiki/w/{resolved_title.replace(' ', '_')}",
            "infobox_type": infobox_type,
            "fields": fields,
            "stale": data.get("_stale", False),
        }

    # ────────────────────────────────────────────────────────────
    # File / image fetching — for inventory icons, NPC sprites, etc.
    # ────────────────────────────────────────────────────────────
    def file_url(
        self, filename: str, *, thumb_width: Optional[int] = None,
    ) -> Optional[str]:
        """Resolve ``File:<filename>`` to its image URL.

        ``filename`` should NOT include the ``File:`` prefix. When
        ``thumb_width`` is set, returns the server-side thumbnail URL
        at that pixel width — invaluable for inventory icons since
        the canonical wiki ``_detail.png`` renders are 500-1000+ px
        and downsampling client-side would be wasteful.
        Returns ``None`` if the file doesn't exist.
        """
        title = filename if filename.lower().startswith("file:") else f"File:{filename}"
        params: Dict[str, Any] = {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "format": "json",
        }
        if thumb_width:
            params["iiurlwidth"] = int(thumb_width)
        data = self._get("imageinfo", params)
        pages = (data.get("query") or {}).get("pages") or {}
        for _pid, page in pages.items():
            if int(_pid) < 0:        # missing page
                continue
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            if thumb_width and info.get("thumburl"):
                return info["thumburl"]
            if info.get("url"):
                return info["url"]
        return None

    def fetch_item_image(
        self, item_name: str,
        *,
        dest_dir: Optional[Path] = None,
        thumb_width: int = 36,
    ) -> Optional[Path]:
        """Fetch the inventory-sized thumbnail for an item.

        Tries ``<Item>_detail.png`` (the canonical inventory render)
        first, falls back to ``<Item>.png`` if missing. Both are
        requested as a server-side thumbnail at ``thumb_width`` px so
        what hits disk is already the right scale for matching against
        in-game inventory slots (~30-36 px wide).

        Saves to ``dest_dir / <slug>.png`` and returns that path; returns
        ``None`` when the wiki has no matching file.
        """
        if not item_name.strip():
            return None
        canonical = item_name.strip().replace(" ", "_")
        canonical = canonical[:1].upper() + canonical[1:]
        slug = _slugify(item_name)

        if dest_dir is None:
            base = self._cache.root if self._cache is not None else Path.cwd()
            dest_dir = base / "items"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{slug}.png"
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        url = (
            self.file_url(f"{canonical}_detail.png", thumb_width=thumb_width)
            or self.file_url(f"{canonical}.png", thumb_width=thumb_width)
        )
        if url is None:
            return None

        try:
            self._bucket.acquire()
            resp = self._session.get(url, timeout=self._timeout, stream=True)
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        except Exception:
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
            return None
        return dest

    # ────────────────────────────────────────────────────────────
    # HTTP path (cache-aware)
    # ────────────────────────────────────────────────────────────
    def _get(self, endpoint_tag: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET with cache. ``endpoint_tag`` is a label for the cache key."""
        cache = self._cache
        if cache is not None:
            cached, stale = cache.get(endpoint_tag, params)
            if cached is not None and not stale:
                return cached

        try:
            self._bucket.acquire()
            resp = self._session.get(BASE_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            if cache is not None:
                cache.set(endpoint_tag, params, data)
            return data
        except Exception as e:
            # Network failure — serve stale if possible, else re-raise.
            if cache is not None:
                cached, _stale = cache.get(endpoint_tag, params, allow_stale=True)
                if cached is not None:
                    result = dict(cached)
                    result["_stale"] = True
                    return result
            raise RuntimeError(f"wiki fetch failed: {type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────


_HTML_TAG = re.compile(r"<[^>]+>")
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")
_TEMPLATE_CALL = re.compile(r"\{\{[^{}]+?\}\}")


def _strip_html(text: str) -> str:
    """Remove HTML tags + collapse whitespace."""
    return re.sub(r"\s+", " ", _HTML_TAG.sub("", text)).strip()


def _wikitext_to_plain(text: str) -> str:
    """Cheap wikitext → plain text.

    Not a full parser — just enough to turn a page body into something
    an LLM can read without choking on syntax.
    """
    if not text:
        return ""
    # [[Link|Label]] → Label;  [[Link]] → Link.
    def _link(m: "re.Match[str]") -> str:
        return m.group(2) if m.group(2) else m.group(3) or ""
    text = _WIKI_LINK.sub(_link, text)
    # Drop template calls entirely — they're mostly noise for LLM consumption.
    # (Infobox parsing uses the raw wikitext, so this stripping only affects
    # plain-text output.)
    prev = None
    while prev != text:
        prev = text
        text = _TEMPLATE_CALL.sub("", text)
    # Collapse table / HTML / heading markup minimally.
    text = _HTML_TAG.sub("", text)
    text = re.sub(r"'''([^']+)'''", r"**\1**", text)
    text = re.sub(r"''([^']+)''", r"*\1*", text)
    text = re.sub(r"^\s*={2,6}\s*([^=]+?)\s*={2,6}\s*$", r"## \1", text, flags=re.M)
    text = re.sub(r"^\s*\|[^\n]*$", "", text, flags=re.M)  # table rows
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────


def default_client(cache_root: Path) -> WikiClient:
    """Build a :class:`WikiClient` with the standard disk cache root."""
    cache = WikiCache(Path(cache_root))
    return WikiClient(cache=cache)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Filesystem-safe lowercase slug. ``Raw trout`` → ``raw_trout``."""
    s = _SLUG_RE.sub("_", name.lower()).strip("_")
    return s or "unknown"
