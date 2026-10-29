"""Finding the table in a spreadsheet (spec § 6.2). An export is rarely a table from its first cell: a title, the organization's name or
"Report run on …" sit above the header, a header can span two rows, columns can be empty and a total can close it. The header row is
scored among the first rows; a person can choose another. Cells are kept as text exactly as written (dates in ISO form)."""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from python_calamine import CalamineWorkbook

from .. import packs

SPREADSHEETS = {'.xlsx', '.xlsm', '.xlsb', '.xls', '.ods'}
FILE_SUFFIXES = SPREADSHEETS | {'.csv'}
SCAN_ROWS = 30
"""How many rows from the top can be the header."""
SAMPLE_ROWS = 20
"""How many rows below a candidate are looked at to judge it."""
_NUMBER = re.compile(r'^[-+]?\d[\d,]*(\.\d+)?%?$')
_DATE = re.compile(r'^(\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})$')


class SheetError(ValueError):
    """The file cannot be read as a table (format, missing sheet, empty)."""


@dataclass
class Table:
    """A sheet read as a table: its header (as written), its rows keyed by it, and what was left out."""

    where: str
    header_row: int
    """1-based, as the spreadsheet numbers it."""
    columns: list[str]
    rows: list[dict[str, str | None]]
    """Each row with its spreadsheet row number under `_row` left to the caller (see `numbered`)."""
    row_numbers: list[int]
    notes: list[str] = field(default_factory=list)
    """The text of the rows above the header (a title, a date of the report)."""
    dropped_columns: int = 0
    dropped_total_rows: int = 0
    guessed: bool = True
    """False when a person chose the header row."""


def cell_text(value: Any) -> str | None:
    """A cell as text, as written: 12345.0 -> '12345', dates in ISO form, empty -> None."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def sheet_names(path: Path) -> list[str]:
    if path.suffix.lower() == '.csv':
        return []
    return list(CalamineWorkbook.from_path(str(path)).sheet_names)


def read_cells(path: Path, sheet: str | None = None) -> tuple[list[list[str | None]], str]:
    """All cells of one sheet (the first, or `sheet`) or of a CSV, as text; and where they came from, for messages."""
    suffix = path.suffix.lower()
    if suffix == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
            raw: list[list[Any]] = list(csv.reader(f))
        where = path.name
    elif suffix in SPREADSHEETS:
        book = CalamineWorkbook.from_path(str(path))
        name = sheet or book.sheet_names[0]
        if name not in book.sheet_names:
            raise SheetError(f'{path.name} has no sheet "{name}" (it has: {", ".join(book.sheet_names)})')
        raw = book.get_sheet_by_name(name).to_python()
        where = f'{path.name}, sheet "{name}"'
    else:
        raise SheetError(f'{path.name}: only {", ".join(sorted(FILE_SUFFIXES))} files can be read')
    cells = [[cell_text(v) for v in row] for row in raw]
    if not any(any(c is not None for c in row) for row in cells):
        raise SheetError(f'{where} is empty')
    return cells, where


def _kind(value: str) -> str:
    if _DATE.match(value):
        return 'date'
    if _NUMBER.match(value):
        return 'number'
    return 'text'


def _is_label(value: str) -> bool:
    return _kind(value) == 'text' and len(value) <= 80 and sum(ch.isdigit() for ch in value) <= len(value) // 2


def _filled(row: list[str | None]) -> list[int]:
    return [i for i, v in enumerate(row) if v is not None]


def _score(cells: list[list[str | None]], i: int, width: int) -> float:
    """How much row i looks like the header: wide, made of distinct labels, above rows that fill its columns with values of one kind."""
    row = cells[i]
    positions = _filled(row)
    if len(positions) < 2:
        return -1.0
    values = [row[p] or '' for p in positions]
    labels = sum(_is_label(v) for v in values) / len(values)
    distinct = len(set(values)) / len(values)
    below = [r for r in cells[i + 1 : i + 1 + SAMPLE_ROWS] if any(c is not None for c in r)]
    if not below:
        return -1.0
    fill = sum(sum(1 for p in positions if p < len(r) and r[p] is not None) for r in below) / (len(positions) * len(below))
    # columns whose values below are not labels (numbers, dates, codes): a header row differs from the data under it
    contrast = 0.0
    for p in positions:
        kinds = [_kind(v) for r in below if p < len(r) and (v := r[p]) is not None]
        if kinds and kinds.count('text') / len(kinds) < 0.5:
            contrast += 1
    contrast /= len(positions)
    near = [v for r in below[:5] for v in r if v is not None]
    below_labels = sum(_is_label(v) for v in near) / max(1, len(near))
    return 2 * len(positions) / width + 2 * labels + distinct + fill + contrast + (1 - below_labels) * 0.5


def guess_header(cells: list[list[str | None]]) -> int:
    """The 0-based index of the row most like a header among the first rows."""
    width = max((len(_filled(r)) for r in cells[: SCAN_ROWS + SAMPLE_ROWS]), default=0) or 1
    scored = [(_score(cells, i, width), i) for i in range(min(SCAN_ROWS, len(cells)))]
    best = max(scored, key=lambda s: (s[0], -s[1]))
    if best[0] < 0:
        raise SheetError('no row looks like a header: the sheet needs a row of column names above its data')
    i = best[1]
    if i > 0 and len(_filled(cells[i - 1])) >= 2 and _second_header_row(cells, i - 1):
        return i - 1  # the lower row of a two-row header sits right on the data and scores best; the header starts above it
    return i


def _second_header_row(cells: list[list[str | None]], i: int) -> bool:
    """A header spanning two rows: a top row of groups with gaps (merged cells), then a row of labels, then data."""
    if i + 2 >= len(cells):
        return False
    top, sub, data = cells[i], cells[i + 1], cells[i + 2]
    sub_values = [v for v in sub if v is not None]
    if len(sub_values) < 2 or sum(_is_label(v) for v in sub_values) / len(sub_values) < 0.8:
        return False
    gaps = [p for p in _filled(sub) if p >= len(top) or top[p] is None]
    data_values = [v for v in data if v is not None]
    data_labels = sum(_is_label(v) for v in data_values) / max(1, len(data_values))
    return bool(gaps) and data_labels < 0.8


def _joined_header(top: list[str | None], sub: list[str | None]) -> list[str | None]:
    """'Term' over 'Start' and 'End' (a merged cell) becomes 'Term Start' and 'Term End'."""
    names: list[str | None] = []
    group: str | None = None
    for p in range(max(len(top), len(sub))):
        upper = top[p] if p < len(top) else None
        lower = sub[p] if p < len(sub) else None
        if upper is not None:
            group = upper if lower is not None else None  # a group spans the gaps to its right; a column of its own does not
        if lower is None:
            names.append(upper)
        else:
            names.append(lower if group is None or group == lower else f'{group} {lower}')
    return names


def read_table(path: Path, sheet: str | None = None, header_row: int | None = None) -> Table:
    """The table in a sheet: its header (found, or the 1-based `header_row` a person chose), and its data rows."""
    cells, where = read_cells(path, sheet)
    if header_row is not None:
        if not 1 <= header_row <= len(cells):
            raise SheetError(f'{where} has no row {header_row}')
        top = header_row - 1
    else:
        top = guess_header(cells)
    first_data = top + 1
    names: list[str | None] = list(cells[top])
    if header_row is None and _second_header_row(cells, top):
        names = _joined_header(cells[top], cells[top + 1])
        first_data = top + 2
    data = cells[first_data:]
    width = max([len(names), *(len(r) for r in data)]) if data else len(names)
    names += [None] * (width - len(names))
    keep = [p for p in range(width) if names[p] is not None or any(p < len(r) and r[p] is not None for r in data)]
    columns: list[str] = []
    seen: dict[str, int] = {}
    for p in keep:
        name = names[p] or f'Column {p + 1}'
        seen[name] = seen.get(name, 0) + 1
        columns.append(name if seen[name] == 1 else f'{name} ({seen[name]})')  # two "Date" columns stay two columns
    rows: list[dict[str, str | None]] = []
    numbers: list[int] = []
    for offset, r in enumerate(data):
        values = [r[p] if p < len(r) else None for p in keep]
        if any(v is not None for v in values):
            rows.append(dict(zip(columns, values, strict=True)))
            numbers.append(first_data + offset + 1)
    dropped_total = 0
    if rows:
        first = next((v for v in rows[-1].values() if v is not None), '')
        if first and packs.looks_like_total(first):
            rows.pop()
            numbers.pop()
            dropped_total = 1
    notes = [' '.join(v for v in r if v is not None) for r in cells[:top] if any(v is not None for v in r)]
    return Table(
        where=where,
        header_row=top + 1,
        columns=columns,
        rows=rows,
        row_numbers=numbers,
        notes=[n[:120] for n in notes],
        dropped_columns=width - len(keep),
        dropped_total_rows=dropped_total,
        guessed=header_row is None,
    )
