"""Languages (DEC-038, adopted from the AMS's `packages/shared/src/languages.ts`). English is the primary language of the interface
and never changes; an organization chooses ONE secondary language from this registry. The registry says how a language is written
(direction and script) so the web app can set `<html lang>`, `<html dir>` and the font stack. Nothing else in the BI assumes a
language (DEC-037)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PRIMARY_LANGUAGE = 'en'

Script = Literal['latin', 'arabic', 'hebrew', 'cjk-sc', 'cjk-tc', 'cjk-jp', 'cjk-kr', 'devanagari', 'bengali', 'cyrillic', 'greek', 'thai']


@dataclass(frozen=True)
class Language:
    code: str
    name_en: str
    native_name: str
    script: Script
    dir: Literal['ltr', 'rtl'] = 'ltr'


LANGUAGES: tuple[Language, ...] = (
    Language('en', 'English', 'English', 'latin'),
    Language('ar', 'Arabic', 'العربية', 'arabic', 'rtl'),
    Language('he', 'Hebrew', 'עברית', 'hebrew', 'rtl'),
    Language('fa', 'Persian', 'فارسی', 'arabic', 'rtl'),
    Language('ur', 'Urdu', 'اردو', 'arabic', 'rtl'),
    Language('ps', 'Pashto', 'پښتو', 'arabic', 'rtl'),
    Language('sd', 'Sindhi', 'سنڌي', 'arabic', 'rtl'),
    Language('ku-Arab', 'Kurdish (Sorani)', 'کوردی', 'arabic', 'rtl'),
    Language('fr', 'French', 'Français', 'latin'),
    Language('es', 'Spanish', 'Español', 'latin'),
    Language('pt', 'Portuguese', 'Português', 'latin'),
    Language('de', 'German', 'Deutsch', 'latin'),
    Language('it', 'Italian', 'Italiano', 'latin'),
    Language('nl', 'Dutch', 'Nederlands', 'latin'),
    Language('sv', 'Swedish', 'Svenska', 'latin'),
    Language('pl', 'Polish', 'Polski', 'latin'),
    Language('tr', 'Turkish', 'Türkçe', 'latin'),
    Language('ru', 'Russian', 'Русский', 'cyrillic'),
    Language('uk', 'Ukrainian', 'Українська', 'cyrillic'),
    Language('el', 'Greek', 'Ελληνικά', 'greek'),
    Language('zh-Hans', 'Chinese (Simplified)', '简体中文', 'cjk-sc'),
    Language('zh-Hant', 'Chinese (Traditional)', '繁體中文', 'cjk-tc'),
    Language('ja', 'Japanese', '日本語', 'cjk-jp'),
    Language('ko', 'Korean', '한국어', 'cjk-kr'),
    Language('hi', 'Hindi', 'हिन्दी', 'devanagari'),
    Language('bn', 'Bengali', 'বাংলা', 'bengali'),
    Language('th', 'Thai', 'ไทย', 'thai'),
    Language('vi', 'Vietnamese', 'Tiếng Việt', 'latin'),
    Language('id', 'Indonesian', 'Bahasa Indonesia', 'latin'),
    Language('ms', 'Malay', 'Bahasa Melayu', 'latin'),
    Language('sw', 'Swahili', 'Kiswahili', 'latin'),
)

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
