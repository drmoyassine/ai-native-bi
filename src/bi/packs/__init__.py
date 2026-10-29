"""Language packs and templates (DEC-037): the only place the BI holds anything about a language or a domain, as data. Code applies
any pack; it never names one. Language packs (`languages/*.yml`) say which words suggest a personal or identifying column, how to
make up values when masking a sample, and how to fold text for search. Templates (`templates/<name>/template.yml`) are configuration an
organization installs, changes or ignores."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent


@dataclass(frozen=True)
class LanguagePack:
    code: str
    letters: re.Pattern[str]
    personal: re.Pattern[str] | None
    identifier: re.Pattern[str] | None
    total: re.Pattern[str] | None
    fake_names: tuple[str, ...]
    fake_upper: str
    fake_lower: str
    strip: re.Pattern[str] | None
    fold: dict[int, str]


def _words(words: list[str], match: str) -> re.Pattern[str] | None:
    if not words:
        return None
    alternatives = '|'.join(re.escape(w) for w in words)
    if match == 'word':
        return re.compile(rf'(^|[\W_])({alternatives})($|[\W_])', re.IGNORECASE)
    return re.compile(f'({alternatives})', re.IGNORECASE)


def _starts(words: list[str], match: str) -> re.Pattern[str] | None:
    """A text that starts with one of the words (spaces inside a word may be any whitespace)."""
    if not words:
        return None
    alternatives = '|'.join(r'\s+'.join(re.escape(part) for part in w.split()) for w in words)
    return re.compile(rf'^\s*({alternatives})' + (r'\b' if match == 'word' else ''), re.IGNORECASE)


def _language(data: dict[str, Any]) -> LanguagePack:
    match = data.get('match', 'word')
    return LanguagePack(
        code=data['code'],
        letters=re.compile(data['letters']),
        personal=_words(data.get('personal_words', []), match),
        identifier=_words(data.get('identifier_words', []), match),
        total=_starts(data.get('total_words', []), match),
        fake_names=tuple(data.get('fake_names', [])),
        fake_upper=data.get('fake_letters_upper', ''),
        fake_lower=data.get('fake_letters_lower', ''),
        strip=re.compile(data['strip']) if data.get('strip') else None,
        fold=str.maketrans(data.get('fold', {})),
    )


@cache
def languages() -> tuple[LanguagePack, ...]:
    """Every language pack shipped. All of them are applied to detection and masking: a personal column is personal in any language."""
    return tuple(_language(yaml.safe_load(p.read_text(encoding='utf-8'))) for p in sorted((ROOT / 'languages').glob('*.yml')))


def fallback() -> LanguagePack:
    """The pack for text in a script no pack covers: the interface's primary language (DEC-038)."""
    return next(p for p in languages() if p.code == 'en')


def pack_for(text: str) -> LanguagePack:
    """The pack whose script the text is written in."""
    return next((p for p in languages() if p.code != 'en' and p.letters.search(text)), fallback())


def looks_personal(column: str) -> bool:
    return any(p.personal is not None and p.personal.search(column) for p in languages())


def looks_identifying(column: str) -> bool:
    return any(p.identifier is not None and p.identifier.search(column) for p in languages())


def looks_like_total(text: str) -> bool:
    """Whether a row's first cell says it is a total ("Total", in any language a pack knows)."""
    return any(p.total is not None and p.total.match(text) for p in languages())


def fold(text: str) -> str:
    """Text with each pack's marks removed and letter variants folded (search matches however a word is written)."""
    for p in languages():
        if p.strip is not None:
            text = p.strip.sub('', text)
        text = text.translate(p.fold)
    return text


@cache
def templates() -> dict[str, dict[str, Any]]:
    """Every template shipped, by name."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / 'templates').glob('*/template.yml')):
        out[path.parent.name] = yaml.safe_load(path.read_text(encoding='utf-8'))
    return out
