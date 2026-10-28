"""Finding a metric by the institution's own words: titles, descriptions, synonyms and explanations in English and Arabic, and the
glossary (docs/context-spec.md section 4). It reads what Cube's `/meta` returns, so it never disagrees with the model."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

_ARABIC_MARKS = re.compile('[\u0610-\u061a\u064b-\u065f\u0670\u0640]')  # diacritics and tatweel
_ALEF = str.maketrans({'\u0623': '\u0627', '\u0625': '\u0627', '\u0622': '\u0627', '\u0649': '\u064a', '\u0629': '\u0647'})
_WORD = re.compile(r'\w+')
MAX_RESULTS = 8


def normalise(text: str) -> str:
    """Lower case, no Arabic marks, one spelling of alef, yeh and teh marbuta."""
    return _ARABIC_MARKS.sub('', unicodedata.normalize('NFKC', text).casefold()).translate(_ALEF)


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
    ar = meta.get('ar') or {}
    out: list[tuple[str, float]] = []
    for text in (member.get('title'), ar.get('title')):
        out += [(t, 3.0) for t in _texts(text)]
    out += [(t, 3.0) for t in _texts(meta.get('synonyms'))]
    out += [(t, 1.0) for t in _texts(member.get('description')) + _texts(ar.get('description')) + _texts(meta.get('knowledge'))]
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


def search(members: list[dict[str, Any]], institution: dict[str, Any], query: str) -> dict[str, Any]:
    """Members and glossary terms matching the query, best first, in either language."""
    found: list[tuple[float, dict[str, Any]]] = []
    for m in members:
        s = score(query, entry_texts(m))
        if s > 0:
            found.append((s, brief(m)))
    terms: list[tuple[float, dict[str, Any]]] = []
    for g in institution.get('glossary', []):
        s = score(
            query,
            [(str(g.get('term', '')), 3.0), (str(g.get('ar', '')), 3.0), (str(g.get('en', '')), 1.0), (str(g.get('ar_meaning', '')), 1.0)],
        )
        if s > 0:
            terms.append((s, g))
    found.sort(key=lambda x: -x[0])
    terms.sort(key=lambda x: -x[0])
    return {'members': [m for _, m in found[:MAX_RESULTS]], 'glossary': [g for _, g in terms[:MAX_RESULTS]]}


def brief(member: dict[str, Any]) -> dict[str, Any]:
    """What an agent or a person reads about one member: its words in both languages."""
    meta = member.get('meta') or {}
    ar = meta.get('ar') or {}
    out: dict[str, Any] = {k: member[k] for k in ('name', 'title', 'kind', 'description', 'cube') if member.get(k) is not None}
    if ar:
        out['ar'] = ar
    if meta.get('synonyms'):
        out['synonyms'] = meta['synonyms']
    if meta.get('knowledge'):
        out['knowledge'] = meta['knowledge']
    if meta.get('metric'):
        out['metric'] = meta['metric']
    return out


def prompt_text(institution: dict[str, Any], budget_chars: int = 8000) -> str:
    """The glossary and instructions as a block for the agent's instructions, within a budget (about 2,000 tokens)."""
    lines: list[str] = []
    if institution.get('instructions'):
        lines += ["The institution's instructions:"] + [f'- {i}' for i in institution['instructions']]
    if institution.get('glossary'):
        lines += ["The institution's glossary:"] + [
            f'- {g.get("term")} ({g.get("ar", "")}): {g.get("en", "")}' for g in institution['glossary']
        ]
    return '\n'.join(lines)[:budget_chars]
