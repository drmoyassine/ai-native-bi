"""The completeness check (docs/context-spec.md section 4): a metric cannot ship without its words."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

MODEL = Path(__file__).parent.parent / 'cube' / 'model'
PERSONAL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{8,}\d')  # an email, or a phone or national-ID-like number
GLOSSARY_CHARS = 8000  # the prompt's budget for the glossary and instructions (about 2,000 tokens)


def load(kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted((MODEL / kind).glob('*.yml')):
        out += yaml.safe_load(path.read_text(encoding='utf-8')).get(kind, [])
    return out


CUBES = load('cubes')
MEMBERS = [(c, m) for c in CUBES for k in ('measures', 'dimensions') for m in c.get(k, []) if m.get('public', True)]


def texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [t for v in items for t in texts(v)]


@pytest.mark.parametrize('cube', CUBES, ids=lambda c: c['name'])
def test_every_cube_has_a_steward_a_version_and_an_arabic_title(cube: dict[str, Any]) -> None:
    meta = cube.get('meta', {})
    assert meta.get('steward') and meta.get('definition_version'), f'{cube["name"]}: steward and definition_version'
    assert (meta.get('ar') or {}).get('title'), f'{cube["name"]}: meta.ar.title'


@pytest.mark.parametrize(('cube', 'member'), MEMBERS, ids=lambda x: x['name'])
def test_every_public_member_has_a_description_and_an_arabic_title(cube: dict[str, Any], member: dict[str, Any]) -> None:
    where = f'{cube["name"]}.{member["name"]}'
    assert member.get('title') and member.get('description'), f'{where}: title and description'
    assert (member.get('meta', {}).get('ar') or {}).get('title'), f'{where}: meta.ar.title'


@pytest.mark.parametrize(('cube', 'member'), [(c, m) for c, m in MEMBERS if (m.get('meta') or {}).get('metric')], ids=lambda x: x['name'])
def test_a_metric_exposed_to_the_ams_has_synonyms_and_an_explanation(cube: dict[str, Any], member: dict[str, Any]) -> None:
    meta = member['meta']
    assert meta.get('synonyms', {}).get('en') and meta.get('synonyms', {}).get('ar'), 'synonyms in both languages'
    assert meta.get('knowledge', {}).get('en') and meta.get('knowledge', {}).get('ar'), 'an explanation in both languages'


def test_the_words_hold_nothing_that_looks_personal() -> None:
    every = texts([CUBES, load('views')])
    assert [t for t in every if PERSONAL.search(t)] == []


def test_the_institution_view_fits_the_prompt_budget() -> None:
    meta = next(v for v in load('views') if v['name'] == 'institution')['meta']
    assert meta['instructions'] and meta['glossary']
    assert sum(len(t) for t in texts([meta['instructions'], meta['glossary']])) < GLOSSARY_CHARS
