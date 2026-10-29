"""The completeness check (docs/context-spec.md section 4): a metric cannot ship without its words. It reads every Cube file a template
ships and every hand-written one in cube/model."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parent.parent
SOURCES = [ROOT / 'cube' / 'model', *sorted((ROOT / 'src' / 'bi' / 'packs' / 'templates').glob('*/cube'))]
PERSONAL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{8,}\d')  # an email, or a phone or national-ID-like number
GLOSSARY_CHARS = 8000  # the prompt's budget for the glossary and instructions (about 2,000 tokens)


def load(kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for base in SOURCES:
        for path in sorted(base.rglob('*.yml')):
            out += (yaml.safe_load(path.read_text(encoding='utf-8')) or {}).get(kind, [])
    return out


CUBES = load('cubes')
MEMBERS = [(c, m) for c in CUBES for k in ('measures', 'dimensions') for m in c.get(k, []) if m.get('public', True)]


def _translated(meta: dict[str, Any] | None) -> set[str]:
    return set((meta or {}).get('translations') or {})


# The languages the model is written in: English (the primary language, DEC-038) and every language any of its words use. No language
# is named here (DEC-037); a model that uses one must use it everywhere.
LANGUAGES = (
    {'en'}
    | {code for c in CUBES for code in _translated(c.get('meta'))}
    | {code for _, m in MEMBERS for code in _translated(m.get('meta'))}
)
OTHER = LANGUAGES - {'en'}


def texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [t for v in items for t in texts(v)]


@pytest.mark.parametrize('cube', CUBES, ids=lambda c: c['name'])
def test_every_cube_has_a_steward_a_version_and_a_title_in_each_language(cube: dict[str, Any]) -> None:
    meta = cube.get('meta', {})
    assert meta.get('steward') and meta.get('definition_version'), f'{cube["name"]}: steward and definition_version'
    for code in OTHER:
        assert ((meta.get('translations') or {}).get(code) or {}).get('title'), f'{cube["name"]}: meta.translations.{code}.title'


@pytest.mark.parametrize(('cube', 'member'), MEMBERS, ids=lambda x: x['name'])
def test_every_public_member_has_a_description_and_a_title_in_each_language(cube: dict[str, Any], member: dict[str, Any]) -> None:
    where = f'{cube["name"]}.{member["name"]}'
    assert member.get('title') and member.get('description'), f'{where}: title and description'
    for code in OTHER:
        assert (((member.get('meta') or {}).get('translations') or {}).get(code) or {}).get('title'), f'{where}: translations.{code}'


@pytest.mark.parametrize(('cube', 'member'), [(c, m) for c, m in MEMBERS if (m.get('meta') or {}).get('metric')], ids=lambda x: x['name'])
def test_a_metric_exposed_to_the_ams_has_synonyms_and_an_explanation(cube: dict[str, Any], member: dict[str, Any]) -> None:
    meta = member['meta']
    for code in LANGUAGES:
        assert meta.get('synonyms', {}).get(code), f'synonyms in {code}'
        assert meta.get('knowledge', {}).get(code), f'an explanation in {code}'


def test_the_words_hold_nothing_that_looks_personal() -> None:
    every = texts([CUBES, load('views')])
    assert [t for t in every if PERSONAL.search(t)] == []


def test_the_glossary_and_instructions_fit_the_prompt_budget() -> None:
    metas = [v.get('meta') or {} for v in load('views')]
    words = [[m.get('instructions'), m.get('glossary')] for m in metas]
    assert sum(len(t) for t in texts(words)) < GLOSSARY_CHARS
