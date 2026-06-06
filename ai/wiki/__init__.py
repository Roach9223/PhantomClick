"""RS3 Wiki MCP surface.

Thin wrapper around the RuneScape MediaWiki API at
``runescape.wiki/api.php``. Three primitives:

- :meth:`WikiClient.search` — full-text search, returns titles + snippets.
- :meth:`WikiClient.page` — rendered page content as Markdown-ish text.
- :meth:`WikiClient.infobox` — parsed ``{{Infobox}}`` key/value dict.

Disk-backed cache under ``debug/wiki_cache/`` with a 24 h TTL. Stale
entries are returned with ``stale: True`` on network failure so
offline usage still works.

The MCP layer (``rs3vision_studio.ui.mcp_bridge._tool_wiki_*``) is the
primary consumer — users don't touch this directly.
"""

from __future__ import annotations

from .cache import WikiCache
from .client import WikiClient, default_client

__all__ = ["WikiClient", "WikiCache", "default_client"]
