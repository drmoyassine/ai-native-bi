"""Languages (DEC-038, adopted from the AMS's `packages/shared/src/languages.ts`). English is the primary language of the interface
and never changes; an organization chooses ONE secondary language from this registry. The registry says how a language is written
(direction and script) so the web app can set `<html lang>`, `<html dir>` and the font stack. Nothing else in the BI assumes a
language (DEC-037)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

PRIMARY_LANGUAGE = 'en'

Script = Literal['latin', 'arabic', 'hebrew', 'cjk-sc', 'cjk-tc', 'cjk-jp', 'cjk-kr', 'devanagari', 'bengali', 'cyrillic', 'greek', 'thai']


@dataclass(frozen=True)
class Language:
    code: str
    name_en: str
    native_name: str
    script: Script
    dir: Literal['ltr', 'rtl'] = 'ltr'


def _registry() -> tuple[Language, ...]:
    entries = yaml.safe_load((Path(__file__).parent / 'packs' / 'registry.yml').read_text(encoding='utf-8'))
    return tuple(Language(e['code'], e['name_en'], e['native_name'], e['script'], e['dir']) for e in entries)


LANGUAGES: tuple[Language, ...] = _registry()
"""The registry (src/bi/packs/registry.yml): data, not code (DEC-037)."""

BY_CODE = {lang.code: lang for lang in LANGUAGES}


def secondary_language_problem(code: str | None) -> str | None:
    """Why `code` cannot be the organization's secondary language, or None when it can (None itself means "none")."""
    if code is None:
        return None
    if code == PRIMARY_LANGUAGE:
        return 'English is always the primary language; choose a different secondary language or none'
    if code not in BY_CODE:
        return f'"{code}" is not a language this application knows'
    return None


def effective_locale(chosen: str | None, default: str, secondary: str | None) -> str:
    """The interface language a person sees: their own choice if still offered, else the organization's default, else English."""
    offered = {PRIMARY_LANGUAGE, *([secondary] if secondary else [])}
    for code in (chosen, default):
        if code in offered:
            return str(code)
    return PRIMARY_LANGUAGE


def _luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else float(((s + 0.055) / 1.055) ** 2.4)

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


MIN_ACCENT_CONTRAST = 4.5


def is_readable_accent(hex_colour: str) -> bool:
    """The accent colour is the background of buttons with white text, so white on it must reach WCAG AA (4.5)."""
    import re

    return bool(re.fullmatch(r'#[0-9a-fA-F]{6}', hex_colour)) and 1.05 / (_luminance(hex_colour) + 0.05) >= MIN_ACCENT_CONTRAST
