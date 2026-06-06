# RS3 Wiki MCP tools

Three MCP tools expose runescape.wiki to Claude so tuning
conversations get grounded facts instead of guesses.

| Tool                   | Returns                                          |
|------------------------|--------------------------------------------------|
| ``wiki_search(q, limit)`` | ``{query, results: [{title, snippet, url}], stale}`` |
| ``wiki_page(title, section?)`` | ``{title, url, text, sections, stale}`` |
| ``wiki_infobox(title)`` | ``{title, url, infobox_type, fields, stale}``   |

``wiki_page.text`` is plain text — wiki markup and HTML stripped. Easy
for Claude to summarise. Use ``section`` to fetch just one heading
when the full page is too long.

``wiki_infobox.fields`` is a flat key/value dict lifted from the
page's first ``{{Infobox}}`` template. Typical keys on a resource
page: ``level``, ``xp``, ``respawn``, ``location``, ``release``,
``members``.

## Caching

Cache lives at ``F:\RS3_AI\debug\wiki_cache\<sha1>.json``, one file
per unique ``(endpoint, params)`` tuple. TTL is 24 h — within that
window ``wiki_search("acadia")`` round-trips in ~15 ms. When the
network fails, stale cache entries are returned with ``stale: true``
so offline usage still works.

Manual cache control: ``rs3vision_studio.wiki.WikiCache(root).clear()``
nukes everything. Useful when a page you care about has been updated
and you want a fresh fetch.

## Rate limiting + etiquette

- Internal 1-request-per-second token bucket keeps us a good
  citizen. Concurrent callers serialise naturally.
- User-Agent header is always set — required by MediaWiki to avoid
  anti-bot rejections.
- Timeout is 10 s; no retries (cache handles transient drops).

## Example chat flow

> User: *"How much XP is an Acadia log?"*
>
> Claude:
> - ``wiki_infobox("Acadia logs")`` → ``{level: 47, xp: 92.5, ...}``
> - "47 Woodcutting, 92.5 XP per log. Decent — 1k logs/hr at
>   Menaphos patch is ~92k xp/hr even without brooch."

> User: *"I keep running out of acadia before the trees respawn."*
>
> Claude:
> - ``wiki_infobox("Acadia tree")`` → ``{respawn: "8–16 seconds", ...}``
> - "Respawn is 8–16 s. Your 6000 ms wait races the lower end —
>   bump it to 12000 to avoid the window."

## Not wired (by design)

- **No auto-populate of New-Task wizard.** The plan explicitly
  defers integration with task creation. Claude can still use the
  tools while chat-building.
- **No GE (Grand Exchange) price feed.** Separate API, different
  rate limits, not needed for tuning.
