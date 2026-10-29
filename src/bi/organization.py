"""The organization's settings (DEC-037, DEC-038): its name, its secondary language, the default interface language and its accent
colour. The BI knows nothing else about the organization; what it reports on is configuration elsewhere (docs/data-model-spec.md)."""

from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, field_validator

from .languages import BY_CODE, LANGUAGES, PRIMARY_LANGUAGE, effective_locale, is_readable_accent, secondary_language_problem

_FIELDS = ('name', 'name_secondary', 'secondary_language', 'default_locale', 'accent_color')


class OrganizationPatch(BaseModel):
    """What an admin changes; a field left out is kept, null clears it."""

    model_config = {'extra': 'forbid'}

    name: str | None = Field(default=None, max_length=200)
    name_secondary: str | None = Field(default=None, max_length=200)
    secondary_language: str | None = None
    default_locale: str | None = None
    accent_color: str | None = None

    @field_validator('secondary_language')
    @classmethod
    def _language(cls, v: str | None) -> str | None:
        problem = secondary_language_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator('accent_color')
    @classmethod
    def _accent(cls, v: str | None) -> str | None:
        if v is not None and not is_readable_accent(v):
            raise ValueError('choose a darker colour: white text on it must reach a contrast of 4.5 (#rrggbb)')
        return v


async def get(pool: AsyncConnectionPool) -> dict[str, Any]:
    async with pool.connection() as conn:
        row = await (
            await conn.execute('select name, name_secondary, secondary_language, default_locale, accent_color from organization')
        ).fetchone()
    assert row is not None
    return dict(zip(_FIELDS, row, strict=True))


async def update(pool: AsyncConnectionPool, patch: OrganizationPatch, user_id: str) -> dict[str, Any]:
    current = await get(pool)
    changes = patch.model_dump(exclude_unset=True)
    merged = {**current, **changes}
    if merged['name'] is None:
        merged['name'] = ''
    if merged['default_locale'] not in (PRIMARY_LANGUAGE, merged['secondary_language']):
        if 'default_locale' in changes:
            raise ValueError('the default language must be English or the secondary language')
        merged['default_locale'] = PRIMARY_LANGUAGE  # the secondary language changed under it
    async with pool.connection() as conn:
        await conn.execute(
            """update organization set name = %s, name_secondary = %s, secondary_language = %s, default_locale = %s,
                                       accent_color = %s, updated_at = now(), updated_by = %s""",
            [
                merged['name'],
                merged['name_secondary'],
                merged['secondary_language'],
                merged['default_locale'],
                merged['accent_color'],
                user_id,
            ],
        )
    return merged


def language_json(code: str) -> dict[str, str]:
    lang = BY_CODE[code]
    return {'code': lang.code, 'name_en': lang.name_en, 'native_name': lang.native_name, 'dir': lang.dir, 'script': lang.script}


def languages_json() -> list[dict[str, str]]:
    return [language_json(lang.code) for lang in LANGUAGES]


async def user_language(pool: AsyncConnectionPool, user_id: str) -> str | None:
    async with pool.connection() as conn:
        row = await (await conn.execute('select language from app_user where id = %s', [user_id])).fetchone()
    return row[0] if row else None


async def set_user_language(pool: AsyncConnectionPool, user_id: str, code: str | None) -> None:
    org = await get(pool)
    if code is not None and code not in (PRIMARY_LANGUAGE, org['secondary_language']):
        raise ValueError("choose English or the organization's secondary language")
    async with pool.connection() as conn:
        await conn.execute('update app_user set language = %s where id = %s', [code, user_id])


async def locale_for(pool: AsyncConnectionPool, user_id: str) -> str:
    org = await get(pool)
    return effective_locale(await user_language(pool, user_id), org['default_locale'], org['secondary_language'])
