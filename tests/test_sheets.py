"""Finding the table in a spreadsheet (spec § 6.2), on made-up sheets shaped like real exports (DEC-011)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from bi.connect.sheets import SheetError, cell_text, read_table

from .fakes import FALL, HEADER, csv_file, students, xlsx


def sheet(path: Path, rows: list[list[Any]]) -> Path:
    book = openpyxl.Workbook()
    ws = book.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    book.save(path)
    return path


def test_cells_are_kept_as_written() -> None:
    values = [12345.0, 1.5, '  BSME ', '', None, True, dt.date(2026, 8, 24)]
    assert [cell_text(v) for v in values] == ['12345', '1.5', 'BSME', None, None, 'true', '2026-08-24']


def test_a_plain_export_has_its_header_on_the_first_row(tmp_path: Path) -> None:
    rows = students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'))
    for path in (xlsx(tmp_path / 'a.xlsx', rows), csv_file(tmp_path / 'a.csv', rows)):
        table = read_table(path)
        assert table.header_row == 1 and table.columns == HEADER and table.notes == []
        assert table.rows[0]['Student ID'] == '1001' and table.rows[0]['Term Start'] == '2026-08-24'
        assert table.row_numbers == [2, 3]


def test_title_rows_above_the_header_are_kept_as_notes_and_not_loaded(tmp_path: Path) -> None:
    data = students(FALL, (1001, 'BSME', 'Bachelor'), (1002, 'BSCE', 'Bachelor'), (1003, 'MSDS', 'Master'))
    path = sheet(
        tmp_path / 't.xlsx', [['Example Polytechnic'], ['Students - Data Banner - Raw', None, 'Run on 2026-10-20'], [], HEADER, *data]
    )
    table = read_table(path)
    assert table.header_row == 4 and table.columns == HEADER
    assert table.notes == ['Example Polytechnic', 'Students - Data Banner - Raw Run on 2026-10-20']
    assert [r['Student ID'] for r in table.rows] == ['1001', '1002', '1003'] and table.row_numbers == [5, 6, 7]


def test_a_header_over_two_rows_is_joined(tmp_path: Path) -> None:
    top = ['Student ID', 'Term', None, 'Program']
    sub = [None, 'Start', 'End', None]
    data = [[1001, dt.date(2026, 8, 24), dt.date(2026, 12, 18), 'BSME'], [1002, dt.date(2026, 8, 24), dt.date(2026, 12, 18), 'BSCE']]
    table = read_table(sheet(tmp_path / 'h.xlsx', [top, sub, *data]))
    assert table.columns == ['Student ID', 'Term Start', 'Term End', 'Program'] and len(table.rows) == 2


def test_empty_columns_a_total_row_and_repeated_names_are_handled(tmp_path: Path) -> None:
    rows: list[list[Any]] = [
        ['Program', None, 'Date', 'Date', 'Students'],
        ['BSME', None, '2026-08-24', '2026-12-18', 120],
        ['BSCE', None, '2026-08-24', '2026-12-18', 80],
        ['Total', None, None, None, 200],
    ]
    table = read_table(sheet(tmp_path / 'x.xlsx', rows))
    assert table.columns == ['Program', 'Date', 'Date (2)', 'Students']
    assert [r['Program'] for r in table.rows] == ['BSME', 'BSCE'] and table.dropped_total_rows == 1 and table.dropped_columns == 1


def test_a_person_can_choose_the_header_row_and_arabic_headers_are_kept(tmp_path: Path) -> None:
    rows = [['تقرير الطلاب'], ['رقم الطالب', 'اسم البرنامج'], ['1001', 'BSME'], ['1002', 'BSCE']]
    path = sheet(tmp_path / 'ar.xlsx', rows)
    assert read_table(path).columns == ['رقم الطالب', 'اسم البرنامج']
    chosen = read_table(path, header_row=1)
    assert chosen.header_row == 1 and not chosen.guessed and chosen.columns[0] == 'تقرير الطلاب'
    with pytest.raises(SheetError, match='has no row 9'):
        read_table(path, header_row=9)


def test_what_cannot_be_read_says_why(tmp_path: Path) -> None:
    with pytest.raises(SheetError, match='no sheet "Nope"'):
        read_table(xlsx(tmp_path / 'a.xlsx', students(FALL, (1, 'A', 'B'))), sheet='Nope')
    with pytest.raises(SheetError, match='is empty'):
        read_table(sheet(tmp_path / 'e.xlsx', [[]]))
    (tmp_path / 'n.pdf').write_bytes(b'%PDF')
    with pytest.raises(SheetError, match='only'):
        read_table(tmp_path / 'n.pdf')
