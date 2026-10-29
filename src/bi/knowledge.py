"""Finding a metric by the organization's own words: titles, descriptions, synonyms and explanations in each of its languages, and the
glossary (docs/context-spec.md section 4). It reads what Cube's `/meta` returns, so it never disagrees with the model."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from . import packs

_WORD = re.compile(r'\w+')
MAX_RESULTS = 8


def normalise(text: str) -> str:
    """Lower case, by Unicode's rules for any script, then folded by the language packs (marks, letter variants)."""
    return packs.fold(unicodedata.normalize('NFKC', text).casefold())


def words(text: str) -> list[str]:
    return _WORD.findall(normalise(text))


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    return []


def entry_texts(member: dict[str, Any]) -> list[tuple[str, float]]:
    """The words of a member with how much each counts: a title or synonym is worth more than an explanation."""
    meta = member.get('meta') or {}
    translations = (meta.get('translations') or {}).values()  # {language code: {title, description}}
    out: list[tuple[str, float]] = []
    for text in [member.get('title'), *(t.get('title') for t in translations)]:
        out += [(t, 3.0) for t in _texts(text)]
    out += [(t, 3.0) for t in _texts(meta.get('synonyms'))]
    descriptions = [member.get('description'), *(t.get('description') for t in translations), meta.get('knowledge')]
    out += [(t, 1.0) for d in descriptions for t in _texts(d)]
    return out


def score(query: str, texts: list[tuple[str, float]]) -> float:
    """0 when nothing matches; a whole phrase beats words, words beat near-spellings."""
    q = normalise(query).strip()
    qwords = words(query)
    if not q or not qwords:
        return 0.0
    best = 0.0
    for text, weight in texts:
        t = normalise(text)
        if q in t:
            best = max(best, weight * 3)
            continue
        twords = words(text)
        hits = 0.0
        for w in qwords:
            if w in twords:
                hits += 1
            elif len(w) > 3 and difflib.get_close_matches(w, twords, n=1, cutoff=0.8):
                hits += 0.7
        if hits:
            best = max(best, weight * hits / len(qwords))
    return best


def search(members: list[dict[str, Any]], words_of: dict[str, Any], query: str) -> dict[str, Any]:
    """Members and glossary terms matching the query, best first, in any of the organization's languages. A glossary entry is
    {term: {language code: text}, meaning: {language code: text}}."""
    found: list[tuple[float, dict[str, Any]]] = []
    for m in members:
        s = score(query, entry_texts(m))
        if s > 0:
            found.append((s, brief(m)))
    terms: list[tuple[float, dict[str, Any]]] = []
    for g in words_of.get('glossary', []):
        s = score(query, [(t, 3.0) for t in _texts(g.get('term'))] + [(t, 1.0) for t in _texts(g.get('meaning'))])
        if s > 0:
            terms.append((s, g))
    found.sort(key=lambda x: -x[0])
    terms.sort(key=lambda x: -x[0])
    return {'members': [m for _, m in found[:MAX_RESULTS]], 'glossary': [g for _, g in terms[:MAX_RESULTS]]}


def brief(member: dict[str, Any]) -> dict[str, Any]:
    """What an agent or a person reads about one member: its words in each language."""
    meta = member.get('meta') or {}
    out: dict[str, Any] = {k: member[k] for k in ('name', 'title', 'kind', 'description', 'cube') if member.get(k) is not None}
    if meta.get('translations'):
        out['translations'] = meta['translations']
    if meta.get('synonyms'):
        out['synonyms'] = meta['synonyms']
    if meta.get('knowledge'):
        out['knowledge'] = meta['knowledge']
    if meta.get('metric'):
        out['metric'] = meta['metric']
    return out


def _glossary_line(entry: dict[str, Any]) -> str:
    term, meaning = entry.get('term'), entry.get('meaning')
    terms = ' / '.join(_texts(term))
    return f'- {terms}: {" / ".join(_texts(meaning))}'


def prompt_text(words_of: dict[str, Any], budget_chars: int = 8000) -> str:
    """The glossary and instructions as a block for the agent's instructions, within a budget (about 2,000 tokens)."""
    lines: list[str] = []
    if words_of.get('instructions'):
        lines += ["The organization's instructions:"] + [f'- {i}' for i in words_of['instructions']]
    if words_of.get('glossary'):
        lines += ["The organization's glossary:"] + [_glossary_line(g) for g in words_of['glossary']]
    return '\n'.join(lines)[:budget_chars]
