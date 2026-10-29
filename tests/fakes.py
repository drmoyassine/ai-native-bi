"""Made-up enrollment exports for tests (DEC-011): never real data, never loaded outside tests."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

import openpyxl

HEADER = ['Student ID', 'Term Code', 'Term', 'Term Start', 'Term End', 'Program', 'Level', 'Status']
FALL = ('202610', 'Fall 2026', dt.date(2026, 8, 24), dt.date(2026, 12, 18))
SPRING = ('202620', 'Spring 2027', dt.date(2027, 1, 18), dt.date(2027, 5, 14))


def students(term: tuple[str, str, dt.date, dt.date], *rows: tuple[int, str, str]) -> list[list[Any]]:
    """Rows of the export: (student id, program, level) in one term, all enrolled."""
    code, label, start, end = term
    return [[sid, int(code), label, start, end, program, level, 'Enrolled'] for sid, program, level in rows]


def xlsx(path: Path, rows: list[list[Any]], header: list[str] = HEADER, sheet: str = 'Enrollment') -> Path:
    book = openpyxl.Workbook()
    ws = book.active
    assert ws is not None
    ws.title = sheet
    ws.append(header)
    for row in rows:
        ws.append(row)
    book.save(path)
    return path


def csv_file(path: Path, rows: list[list[Any]], header: list[str] = HEADER) -> Path:
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows([[v.isoformat() if isinstance(v, dt.date) else v for v in row] for row in rows])
    return path


def template_fields(event: str = 'enrollment', template: str = 'higher-education') -> list[Any]:
    """The parts of a template's event, as the mapping sees them (the tests' made-up data is the template's, DEC-037)."""
    from bi import definitions, mapping, packs

    body = definitions.parse('event', packs.templates()[template]['events'][event])
    return [mapping.to_field(p) for p in body.parts]
