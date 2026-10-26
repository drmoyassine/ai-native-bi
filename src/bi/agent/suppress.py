"""Small counts are hidden before anything reaches the model (DEC-017; the threshold is set by the privacy rules, TASK-002).

Primary suppression only: a count under the threshold becomes null and the row says so. Differencing across several overlapping
queries is not prevented here (complementary suppression is part of TASK-008); the model is also told not to try."""

from __future__ import annotations

from typing import Any

COUNT_AGG_TYPES = {'count', 'countDistinct', 'countDistinctApprox'}


def count_measures(members: list[dict[str, Any]]) -> set[str]:
    """The measures that count things (people, rows): the only ones small-cell rules apply to."""
    return {m['name'] for m in members if m.get('kind') == 'measure' and m.get('agg_type') in COUNT_AGG_TYPES}


def number(value: Any) -> float | None:
    """Cube answers numbers as text."""
    if value is None or value == '':
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float('inf'), float('-inf')) else None


def suppress_rows(rows: list[dict[str, Any]], measures: list[str], counts: set[str], threshold: int) -> tuple[list[dict[str, Any]], int]:
    """Rows with the measures as numbers (null where Cube had none), and counts between 1 and threshold-1 hidden as null.
    Returns the rows and how many cells were hidden; each changed row lists them under `suppressed`."""
    out: list[dict[str, Any]] = []
    hidden = 0
    for r in rows:
        row = dict(r)
        cells: list[str] = []
        for m in measures:
            n = number(r.get(m))
            if m in counts and n is not None and 0 < n < threshold:
                row[m] = None
                cells.append(m)
                hidden += 1
            else:
                row[m] = int(n) if n is not None and n.is_integer() else n
        if cells:
            row['suppressed'] = cells
        out.append(row)
    return out, hidden
