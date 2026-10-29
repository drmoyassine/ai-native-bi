"""The BI knows no organisation, industry or language (DEC-037, CLAUDE.md rule 0). The code, its prompts and its interface name no
domain and assume no language; anything domain-specific is a template or a language pack (src/bi/packs), which are data. Templates'
models that still live outside a template wait in WAITING until data model M0b moves them (docs/data-model-spec.md section 12); the
list only shrinks."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCANNED = [ROOT / 'src' / 'bi', ROOT / 'web' / 'src', ROOT / 'cube' / 'model']
SUFFIXES = {'.py', '.sql', '.yml', '.yaml', '.ts', '.tsx', '.css', '.html'}
PACKS = ROOT / 'src' / 'bi' / 'packs'

# Words that name a domain. Broad on purpose: a neutral use is allowed by name below, with a reason.
DOMAIN = re.compile(
    r'student|enrol|registrar|semester|faculty|campus|\bcourses?\b|curricul|\bprogram(me)?s?\b|term[ _]code|\bgpa\b|tuition|alumn'
    r'|patient|clinic|hospital|diagnos|customer|invoice|retail|shopper|employee|payroll|institution',
    re.IGNORECASE,
)

# Files the higher-education template's models still live in, until generation installs them (M0b). Never add to this list.
WAITING = {
    'cube/model/cubes/enrollment.yml',
    'cube/model/views/organization.yml',
    'src/bi/transform/models/analytics/enrollment.sql',
    'src/bi/transform/models/staging/stg_enrollment.sql',
    'src/bi/transform/models/schema.yml',
}

# A word allowed in one file, and why.
ALLOWED = {
    ('src/bi/contract.py', 'semester'): "the AMS's contract: a schedule's period names (the AMS owns the contract, CLAUDE.md rule 1)",
    ('src/bi/mcp/principal.py', 'institution'): "the AMS's token: the scope type meaning the whole organization (contract 6.2)",
    ('src/bi/config.py', 'institution'): 'the renamed environment variable, still read under its old name for one release',
    ('src/bi/migrations/0011_setup_agent.sql', 'institution'): 'an applied migration, never edited (CLAUDE.md rule 7)',
}


def files() -> list[Path]:
    out: list[Path] = []
    for base in SCANNED:
        for path in base.rglob('*'):
            if path.suffix not in SUFFIXES or not path.is_file() or PACKS in path.parents:
                continue
            if '__pycache__' in path.parts or path.name.endswith(('.test.ts', '.test.tsx')):
                continue
            out.append(path)
    return sorted(out)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_no_code_names_a_domain() -> None:
    found: list[str] = []
    for path in files():
        if rel(path) in WAITING:
            continue
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for m in DOMAIN.finditer(line):
                word = m.group(0).lower()
                if not any(rel(path) == f and word.startswith(w) for f, w in ALLOWED):
                    found.append(f'{rel(path)}:{n}: "{m.group(0)}"')
    assert found == [], 'domain words outside templates (DEC-037):\n' + '\n'.join(found)


def test_no_code_assumes_a_language() -> None:
    """Letters outside ASCII in code mean a language is built in; they belong in a language pack. Typography (curly quotes,
    ellipses) is fine."""
    found: list[str] = []
    for path in files():
        if rel(path) in WAITING:
            continue
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if any(ord(ch) > 127 and ch.isalpha() for ch in line):
                found.append(f'{rel(path)}:{n}')
    assert found == [], 'letters of a language outside language packs (DEC-037):\n' + '\n'.join(found)


def test_the_waiting_list_only_holds_what_still_waits() -> None:
    """A file that no longer names a domain leaves the list, so the list can only shrink to nothing."""
    for name in WAITING:
        path = ROOT / name
        assert path.exists(), f'{name} is gone: remove it from WAITING'
        assert DOMAIN.search(path.read_text(encoding='utf-8')), f'{name} names no domain any more: remove it from WAITING'


def test_templates_and_language_packs_are_the_only_domain_content() -> None:
    from bi import packs

    assert packs.templates(), 'templates ship as data'
    assert {p.code for p in packs.languages()} >= {'en'}
    assert packs.looks_personal('Email') and packs.looks_identifying('Record ID')


def test_language_packs_bring_the_words_code_used_to_hold() -> None:
    from bi import packs

    assert packs.looks_like_total('Grand  Total') and packs.looks_like_total('total') and not packs.looks_like_total('Totals of x')
    arabic_total = next(p for p in packs.languages() if p.code != 'en' and p.total is not None)
    assert arabic_total.total is not None
    assert packs.pack_for('مريم').code != 'en' and packs.pack_for('Maria').code == 'en'
    assert packs.pack_for('Мария').code == 'en'  # a script no pack covers falls back to the primary language's
