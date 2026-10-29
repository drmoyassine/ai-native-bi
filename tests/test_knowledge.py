from __future__ import annotations

from typing import Any

from bi import knowledge

HEADCOUNT: dict[str, Any] = {
    'name': 'enrollment.headcount',
    'title': 'Headcount',
    'kind': 'measure',
    'description': 'Distinct students on theales roster.',
    'cube': 'Enrollment',
    'meta': {
        'metric': 'enrollment_headcount',
        'ar': {'title': 'عدد الطلاب', 'description': ''},
        'synonyms': {'en': ['number of students', 'student count'], 'ar': ['عدد المسجلين']},
        'knowledge': {'en': 'Counts each student once per term.'},
    },
}
PROGRAM: dict[str, Any] = {'name': 'enrollment.program', 'title': 'Program', 'kind': 'dimension', 'cube': 'Enrollment', 'meta': {}}
INSTITUTION: dict[str, Any] = {
    'glossary': [{'term': 'Census date', 'ar': 'تاريخ الإحصاء', 'en': 'The day a roster is frozen.'}],
    'instructions': ['Term codes are year plus 10 for fall.'],
}


def names(query: str) -> list[str]:
    return [m['name'] for m in knowledge.search([HEADCOUNT, PROGRAM], INSTITUTION, query)['members']]


def test_finds_a_metric_by_a_synonym_in_either_language() -> None:
    assert names('number of students') == ['enrollment.headcount']
    assert names('عدد المسجلين') == ['enrollment.headcount']
    assert names('عدد الطلاب') == ['enrollment.headcount']


def test_forgives_misspellings_and_arabic_spelling_variants() -> None:
    assert names('headcont') == ['enrollment.headcount']
    assert names('عدد المسجلين'.replace('\u0627', '\u0623')) == ['enrollment.headcount']


def test_an_explanation_is_searchable_and_nothing_matches_nonsense() -> None:
    assert names('once per term') == ['enrollment.headcount']
    assert names('graduation') == []


def test_the_glossary_is_searched_too() -> None:
    found = knowledge.search([], INSTITUTION, 'census')
    assert [g['term'] for g in found['glossary']] == ['Census date']
    assert knowledge.search([], INSTITUTION, 'تاريخ الإحصاء')['glossary']


def test_the_prompt_carries_instructions_and_glossary_within_its_budget() -> None:
    text = knowledge.prompt_text(INSTITUTION)
    assert 'Term codes are year plus 10' in text and 'Census date' in text
    assert len(knowledge.prompt_text(INSTITUTION, budget_chars=20)) == 20
    assert knowledge.prompt_text({}) == ''
