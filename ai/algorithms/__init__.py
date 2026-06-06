"""Algorithms that layer on top of the rs3vision native primitives.

These live in the Studio (not the rs3vision library) because the
algorithms here are glue — they compose `rv.color.find`, `rv.tpa.cluster`,
etc. into higher-level matchers (DTM, bitmap). If profiling shows we
need more speed, the inner loops can migrate down to Rust later.
"""
