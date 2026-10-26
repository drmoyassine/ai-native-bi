from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from .config import origin_of
from .contract import CollectRequest, Issue

_BEARER = re.compile(r'^Bearer (.+)$')


def key_matches(header: str | None, key: str) -> bool:
    """Constant-time check of the AMS's bearer key."""
    m = _BEARER.match(header or '')
    given = m.group(1) if m else ''
    a = hashlib.sha256(given.encode()).digest()
    b = hashlib.sha256(key.encode()).digest()
    return len(given) > 0 and hmac.compare_digest(a, b)


@dataclass
class Accepted:
    id: str
    repeat: bool
    ok: Literal[True] = True


@dataclass
class Refused:
    issues: list[Issue] = field(default_factory=list)
    status: Literal[400, 422] = 422
    ok: Literal[False] = False


def _issues(error: ValidationError) -> list[Issue]:
    return [Issue(path='.'.join(str(p) for p in e['loc']), message=e['msg']) for e in error.errors()]


async def accept_collect(pool: AsyncConnectionPool, body: Any, ams_origin: str) -> Accepted | Refused:
    """Takes one request of the AMS (contract 3.6) and keeps it for the worker. The callback address must be on the AMS's origin and be
    the run's own supply route, so a caller cannot make the BI post anywhere else. The same attempt sent twice is kept once."""
    try:
        req = CollectRequest.model_validate(body)
    except ValidationError as e:
        return Refused(issues=_issues(e))
    cb = urlsplit(req.callback_url)
    expected = f'/api/bi/v0/runs/{quote(req.run_id, safe="")}/supply'
    try:
        origin = origin_of(req.callback_url)
    except ValueError:
        origin = ''
    if origin != ams_origin or not cb.path.endswith(expected) or cb.query or cb.fragment:
        return Refused(issues=[Issue(path='callbackUrl', message=f'the callback must be {ams_origin}...{expected}')])
    token_hash = hashlib.sha256(req.callback_token.encode()).hexdigest()
    stored = req.model_dump(mode='json', exclude={'callback_token'}, exclude_unset=True)
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """insert into collect_request (run_id, token_hash, callback_token, callback_url, request) values (%s, %s, %s, %s, %s)
                   on conflict (run_id, token_hash) do update set run_id = excluded.run_id
                   returning id::text, (xmax = 0) as inserted""",
                [req.run_id, token_hash, req.callback_token, req.callback_url, Jsonb(stored)],
            )
        ).fetchone()
    assert row is not None
    return Accepted(id=row[0], repeat=not row[1])
