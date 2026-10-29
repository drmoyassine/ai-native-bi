"""Masked sample rows for the setup agent (DEC-032, DEC-035; docs/setup-agent-spec.md § 3). While a source is being set up, a few rows
help the agent tell a code from a name. Before any row leaves the BI every value is made safe, by a pure function of the
column's profile kind and the value, in code and not in a prompt:

* personal columns get made-up values of the same shape and script (a name becomes another name, an email an example address);
* identifiers keep their shape with other digits and letters, the same value always becoming the same fake, so repeats stay repeated;
* free text becomes a note of its length;
* a category value rarer than the suppression threshold in the whole table becomes "[rare value]";
* a column nobody classified is treated as free text, never passed through;
* codes, dates, numbers, booleans and the common category values go as they are, which is what the agent needs.

Only a BI admin's setup work sends a sample, only to a provider an admin marked "may see sample rows", and every sample is logged."""

from __future__ import annotations

import datetime as dt
import random
import re
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .. import packs

SAMPLE_ROWS = 20
"""DEC-032's limit: the most rows of a table that may be sent (a setting can only lower it)."""
RARE = '[rare value]'
_ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')
FREE_TEXT_KINDS = {'text', 'other', None}
PASS_THROUGH = {'category', 'boolean', 'date', 'number'}
IDENTIFYING = {'personal', 'identifier'}


class Masker:
    """Makes one sample safe. The fakes are drawn from a random source nobody can reproduce, and a value always maps to the same fake
    within the sample, so a repeated person stays one person."""

    def __init__(self, profile: dict[str, dict[str, Any]], rng: random.Random | None = None) -> None:
        self.profile = profile
        self.rng = rng or random.SystemRandom()
        self._fakes: dict[tuple[str, str], str] = {}
        self._emails = 0

    def mask(self, column: str, value: Any) -> Any:
        if value is None:
            return None
        info = self.profile.get(column) or {}
        kind = info.get('kind')
        text = value if isinstance(value, str) else str(value)
        if kind == 'personal':
            return self._personal(column, text)
        if kind == 'identifier':
            return self._same_shape(column, text)
        if kind in PASS_THROUGH:
            if kind == 'category' and not self._common(info, text):
                return RARE
            return value
        return f'[text, {len(text)} characters]'  # free text, and any column nobody classified

    @staticmethod
    def _common(info: dict[str, Any], text: str) -> bool:
        """Whether this category value is common enough to be named in the profile (at or above the suppression threshold)."""
        return any(str(v['value']) == text for v in info.get('values', []))

    def _fake(self, column: str, text: str, make: Any) -> str:
        key = (column, text)
        if key not in self._fakes:
            for _ in range(20):  # a fake is never the original
                fake = make()
                if fake != text:
                    break
            self._fakes[key] = fake
        return self._fakes[key]

    def _personal(self, column: str, text: str) -> str:
        if '@' in text:

            def email() -> str:
                self._emails += 1
                return f'person{self._emails}@example.org'

            return self._fake(column, text, email)
        if _ISO_DATE.match(text):

            def date() -> str:
                d = dt.date(1990, 1, 1) + dt.timedelta(days=self.rng.randrange(0, 365 * 15))
                return d.isoformat() + text[10:]

            return self._fake(column, text, date)
        letters = re.sub(r'[\W\d_]+', ' ', text).split()
        if letters and len(letters) == len(text.split()):  # words only: a name
            pool = packs.pack_for(text).fake_names or packs.fallback().fake_names  # made-up names in the text's own script
            return self._fake(column, text, lambda: ' '.join(self.rng.choice(pool) for _ in text.split()))
        return self._same_shape(column, text)

    def _same_shape(self, column: str, text: str) -> str:
        def make() -> str:
            out = []
            for ch in text:
                if ch.isdigit():
                    out.append(str(self.rng.randrange(10)))
                elif ch.isalpha():  # a letter of the pack for its script; a script no pack covers gets the fallback's letters
                    pack = packs.pack_for(ch)
                    letters = (pack.fake_upper if ch.isupper() else pack.fake_lower) or pack.fake_lower or pack.fake_upper
                    out.append(self.rng.choice(letters))
                else:
                    out.append(ch)
            return ''.join(out)

        return self._fake(column, text, make)

    def row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {c: self.mask(c, v) for c, v in row.items()}

    def summary(self, columns: list[str]) -> dict[str, str]:
        """How each column of the sample was treated (logged, and told to the person)."""
        out: dict[str, str] = {}
        for c in columns:
            kind = (self.profile.get(c) or {}).get('kind')
            out[c] = 'replaced' if kind in IDENTIFYING else 'as is' if kind in PASS_THROUGH else 'hidden'
        return out


def masked_columns(summary: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for column, how in summary.items():
        groups.setdefault(how, []).append(column)
    return groups


async def draw(pool: AsyncConnectionPool, schema: str, table: str, sync_id: str, n: int = SAMPLE_ROWS) -> list[dict[str, Any]]:
    """At most `n` random rows of one sync's data (the BI's own columns left out). Runs in the worker only."""
    n = max(1, min(n, SAMPLE_ROWS))
    async with pool.connection() as conn:
        cur = await conn.execute(
            sql.SQL('select * from {} where _bi_sync_id = %s order by random() limit {}').format(
                sql.Identifier(schema, table), sql.Literal(n)
            ),
            [sync_id],
        )
        names = [c.name for c in cur.description or []]
        rows = await cur.fetchall()
    keep = [i for i, c in enumerate(names) if not c.startswith(('_bi_', '_dlt_'))]
    return [{names[i]: row[i] for i in keep} for row in rows]


async def log_sample(
    pool: AsyncConnectionPool,
    *,
    user_id: str | None,
    sync_id: str,
    provider_id: str,
    model_id: str,
    purpose: str,
    rows: int,
    masked: dict[str, str],
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """insert into sample_log (user_id, sync_id, provider_id, model_id, purpose, rows, masked)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [user_id, sync_id, provider_id, model_id, purpose, rows, Jsonb(masked)],
        )
