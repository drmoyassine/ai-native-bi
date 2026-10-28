"""Masked samples (DEC-032): nothing identifying survives, shapes and repeats do, rare categories are hidden, and unclassified columns are
treated as free text. These are the privacy guarantees of the setup agent, so they are checked as properties over many random values."""

from __future__ import annotations

import random
import re
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from bi.connect.sample import RARE, Masker, masked_columns

PROFILE: dict[str, dict[str, Any]] = {
    'Name': {'kind': 'personal'},
    'Email': {'kind': 'personal'},
    'Phone': {'kind': 'personal'},
    'Birth': {'kind': 'personal'},
    'Student ID': {'kind': 'identifier'},
    'Term': {'kind': 'category', 'values': [{'value': '202610', 'rows': 30}, {'value': '202620', 'rows': 12}]},
    'Start': {'kind': 'date'},
    'Credits': {'kind': 'number'},
    'Notes': {'kind': 'text'},
    'Mystery': {'kind': None},
}
SAMPLE = [
    {'Name': 'Hanan Saleh', 'Email': 'hanan@uni.edu', 'Phone': '+973 3612 4455', 'Birth': '2004-05-17', 'Student ID': '202600017',
     'Term': '202610', 'Start': '2026-08-24', 'Credits': '15', 'Notes': 'asked about housing', 'Mystery': 'whatever'},
    {'Name': 'حنان صالح', 'Email': 'other@uni.edu', 'Phone': '+973 3807 2190', 'Birth': '2003-01-02', 'Student ID': '202600017',
     'Term': 'RARE-TERM', 'Start': '2026-08-24', 'Credits': '12', 'Notes': 'visa', 'Mystery': 'x'},
]  # fmt: skip


def shape(text: str) -> str:
    return re.sub(r'[A-Za-z]', 'a', re.sub(r'\d', '9', text))


def test_nothing_identifying_survives_and_common_codes_dates_and_numbers_do() -> None:
    masker = Masker(PROFILE, random.Random(1))
    masked = [masker.row(r) for r in SAMPLE]
    text = str(masked)
    for original in ('Hanan', 'Saleh', 'حنان', 'صالح', 'hanan@', 'other@', '3612 4455', '3807 2190', '2004-05-17', '2003-01-02',
                     '202600017', 'asked about housing', 'visa', 'whatever'):  # fmt: skip
        assert original not in text, original
    assert [m['Term'] for m in masked] == ['202610', RARE]  # a rare category is hidden, a common one kept
    assert [m['Start'] for m in masked] == ['2026-08-24', '2026-08-24'] and [m['Credits'] for m in masked] == ['15', '12']
    assert masked[0]['Notes'] == '[text, 19 characters]' and masked[1]['Mystery'] == '[text, 1 characters]'  # unclassified: hidden
    assert masked[0]['Email'] == 'person1@example.org' and masked[1]['Email'] == 'person2@example.org'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', masked[0]['Birth']) and masked[0]['Birth'] != '2004-05-17'


def test_shapes_scripts_and_repeats_are_kept() -> None:
    masker = Masker(PROFILE, random.Random(2))
    a, b = (masker.row(r) for r in SAMPLE)
    assert shape(a['Phone']) == shape('+973 3612 4455') and shape(a['Student ID']) == '999999999'
    assert a['Student ID'] == b['Student ID']  # the same student stays one student
    assert re.fullmatch(r'[A-Za-z]+ [A-Za-z]+', a['Name']) and re.fullmatch(r'[؀-ۿ]+ [؀-ۿ]+', b['Name'])
    assert masker.row(SAMPLE[0]) == a  # and within one sample, the same value always gives the same fake


def test_missing_values_stay_missing_and_a_summary_says_what_was_done() -> None:
    masker = Masker(PROFILE)
    assert masker.mask('Name', None) is None and masker.mask('Notes', None) is None
    how = masker.summary(['Name', 'Student ID', 'Term', 'Notes', 'Mystery'])
    assert how == {'Name': 'replaced', 'Student ID': 'replaced', 'Term': 'as is', 'Notes': 'hidden', 'Mystery': 'hidden'}
    assert masked_columns(how) == {'replaced': ['Name', 'Student ID'], 'as is': ['Term'], 'hidden': ['Notes', 'Mystery']}


text_values = st.text(alphabet=st.characters(categories=['L', 'N', 'P', 'Z']), min_size=3, max_size=40).filter(
    lambda s: any(c.isalnum() for c in s)
)


@settings(max_examples=200, deadline=None)
@given(value=text_values, kind=st.sampled_from(['personal', 'identifier', 'text', None]), seed=st.integers(0, 10_000))
def test_a_personal_identifier_or_free_text_value_never_comes_out_as_it_went_in(value: str, kind: str | None, seed: int) -> None:
    out = Masker({'c': {'kind': kind}}, random.Random(seed)).mask('c', value)
    assert out != value
    if kind in (None, 'text'):
        assert value not in str(out)  # a free-text value is gone entirely


@settings(max_examples=100, deadline=None)
@given(values=st.lists(st.text(alphabet='0123456789', min_size=5, max_size=12), min_size=2, max_size=30), seed=st.integers(0, 10_000))
def test_identifiers_keep_their_shape_and_their_repeats(values: list[str], seed: int) -> None:
    masker = Masker({'id': {'kind': 'identifier'}}, random.Random(seed))
    out = [masker.mask('id', v) for v in values]
    assert [len(o) for o in out] == [len(v) for v in values] and all(o.isdigit() for o in out)
    for i, a in enumerate(values):
        for j, b in enumerate(values):
            assert (out[i] == out[j]) == (a == b)  # equal in, equal out; different in, different out
            if a != b and out[i] == out[j]:  # pragma: no cover (guarded by the assert above)
                raise AssertionError('two students merged')
