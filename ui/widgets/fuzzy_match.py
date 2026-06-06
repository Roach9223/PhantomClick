"""Tiny subsequence-matching scorer for the command palette.

We don't pull in a fuzzy library because the command set is small (~30
items) and the desired behavior is opinionated: prefer matches at word
boundaries, prefer consecutive runs, penalize gaps. This is well below
30 lines of real logic — a dependency would be more code than the impl.

Returns ``(score, indices)`` where higher score is a better match. ``score``
is ``-1`` if the query is not a subsequence of the target.
"""

from __future__ import annotations

from typing import List, Tuple


def score(query: str, target: str) -> Tuple[int, List[int]]:
    if not query:
        return 0, []
    q = query.lower()
    t = target.lower()
    qi = 0
    indices: List[int] = []
    last_match = -2
    pts = 0
    for ti, ch in enumerate(t):
        if qi < len(q) and ch == q[qi]:
            indices.append(ti)
            # Bonus: word-start (preceded by space, separator, or start of string).
            prev = t[ti - 1] if ti > 0 else " "
            if prev in " -_/.|":
                pts += 8
            elif ti == 0:
                pts += 10
            else:
                pts += 1
            # Bonus: consecutive characters.
            if ti == last_match + 1:
                pts += 4
            last_match = ti
            qi += 1
            if qi == len(q):
                break
    if qi < len(q):
        return -1, []
    # Tie-breaker: shorter target wins, so we don't always show "Setting" before "Set".
    pts -= len(target) // 16
    return pts, indices
