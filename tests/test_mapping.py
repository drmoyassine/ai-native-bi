"""Matching a layout's columns to the parts a dataset needs (DEC-026, DEC-029): by own name first, then by the names exports use, never
to a column whose profile does not fit the part. The whole flow (review, approval, layouts kept apart) is in tests/test_connect.py."""

from __future__ import annotations

import pytest

from bi import mapping

from .fakes import template_fields

FIELDS = template_fields()

EXPORT = ['Student Number', 'Semester', 'Semester Label', 'Start Date', 'Major', 'Student Level', 'Enrollment Status', 'Advisor Notes']


def test_columns_are_matched_by_their_own_name_first_then_by_the_names_exports_use() -> None:
    exact, ok = mapping.propose(FIELDS, ['student_id', 'Term Code', 'TERM', 'term start', 'extra'])
    assert ok and exact['student_id'] == 'student_id' and exact['term_code'] == 'Term Code' and exact['term'] == 'TERM'
    assert exact['term_start'] == 'term start' and exact['program'] is None
    by_label, ok = mapping.propose(FIELDS, ['Student ID', 'Term code', 'Term start date'])
    assert ok and by_label['term_start'] == 'Term start date'  # the plain label counts as the part's own name
    guess, ok = mapping.propose(FIELDS, EXPORT)
    assert not ok  # every needed part is found, but not by its own name: a person looks
    assert guess['student_id'] == 'Student Number' and guess['term_code'] == 'Semester' and guess['term_start'] == 'Start Date'
    assert guess['program'] == 'Major' and guess['term'] == 'Semester Label'
    # a column named by one part is not taken by another through an alias
    assert mapping.propose(FIELDS, ['Term', 'Student ID', 'Term Start'])[0]['term_code'] is None


def test_arabic_names_match_and_a_column_whose_profile_does_not_fit_is_never_proposed() -> None:
    found, _ = mapping.propose(FIELDS, ['رقم الطالب', 'الفصل', 'بداية الفصل', 'المستوى'])
    assert found['student_id'] == 'رقم الطالب' and found['term_code'] == 'الفصل' and found['level'] == 'المستوى'
    kinds = {'Start Date': 'category', 'Student Number': 'personal', 'Semester': 'date'}
    unfit, _ = mapping.propose(FIELDS, ['Student Number', 'Semester', 'Start Date'], kinds)
    assert unfit['term_start'] is None  # not dates
    assert unfit['student_id'] is None  # personal data is mapped only by a person
    assert unfit['term_code'] is None  # a date is not a code


def test_a_mapping_must_name_every_needed_part_once_and_only_columns_the_data_has() -> None:
    with pytest.raises(mapping.MappingError, match='no column is chosen for: Term code'):
        mapping.check('enrollment', FIELDS, {'student_id': 'a', 'term_start': 'b'}, ['a', 'b'])
    with pytest.raises(mapping.MappingError, match='no column "zzz"'):
        mapping.check('enrollment', FIELDS, {'student_id': 'zzz'}, ['a'])
    with pytest.raises(mapping.MappingError, match='only one part'):
        mapping.check('enrollment', FIELDS, {'student_id': 'a', 'term_code': 'a', 'term_start': 'b'}, ['a', 'b'])
    with pytest.raises(mapping.MappingError, match='not a part'):
        mapping.check('enrollment', FIELDS, {'shoe_size': 'a'}, ['a'])
    mapping.check('enrollment', FIELDS, {'student_id': 'a', 'term_code': 'b', 'term_start': 'c', 'program': None}, ['a', 'b', 'c'])
