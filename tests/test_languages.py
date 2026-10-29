from __future__ import annotations

from bi.languages import BY_CODE, PRIMARY_LANGUAGE, effective_locale, is_readable_accent, secondary_language_problem


def test_the_registry_says_how_each_language_is_written() -> None:
    assert BY_CODE[PRIMARY_LANGUAGE].dir == 'ltr'
    assert {c for c, lang in BY_CODE.items() if lang.dir == 'rtl'} >= {'ar', 'he', 'fa', 'ur'}
    assert BY_CODE['ja'].script == 'cjk-jp'


def test_a_secondary_language_is_a_known_one_other_than_english() -> None:
    assert secondary_language_problem(None) is None
    assert secondary_language_problem('fr') is None
    assert secondary_language_problem('en') is not None
    assert secondary_language_problem('klingon') is not None


def test_the_interface_language_falls_back_to_what_is_offered() -> None:
    assert effective_locale('ar', 'en', 'ar') == 'ar'
    assert effective_locale('ar', 'en', None) == 'en'  # the organization dropped Arabic
    assert effective_locale(None, 'fr', 'fr') == 'fr'
    assert effective_locale(None, 'de', 'fr') == 'en'


def test_an_accent_must_carry_white_text() -> None:
    assert is_readable_accent('#1d3557') and is_readable_accent('#000000')
    assert not is_readable_accent('#ffff00') and not is_readable_accent('#fff') and not is_readable_accent('red')
