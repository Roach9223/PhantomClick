"""Per-section pages for the NavRail-driven QStackedWidget shell.

Each page is a thin wrapper that places one or two existing :class:`Card`
widgets into a layout. Pages do not own state — App and the underlying
cards do — so future card swaps don't ripple through the page layer.
"""
