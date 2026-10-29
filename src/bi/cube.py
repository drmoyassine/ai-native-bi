"""The BI's client for Cube's REST API: every read of a KPI goes through it (DEC-004, CLAUDE.md rule 5)."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
import jwt


class CubeError(RuntimeError):
    """Cube refused the query or could not be reached (the job is retried)."""


class CubeNoData(CubeError):
    """The warehouse table behind the query does not exist yet: nothing has been loaded for it. No data, not a failure (rule 3)."""


# PostgreSQL's words when dbt has not built the table a cube reads: before the first file of a dataset is loaded.
_NO_TABLE = re.compile(r'relation "[^"]+" does not exist', re.IGNORECASE)


class CubeClient:
    def __init__(self, client: httpx.AsyncClient, api_url: str, api_secret: str, timeout_s: float = 60, wait_s: float = 1) -> None:
        self._client = client
        self._url = api_url.rstrip('/') + '/cubejs-api/v1'
        self._secret = api_secret
        self._timeout_s = timeout_s
        self._wait_s = wait_s

    def _token(self) -> str:
        now = int(time.time())
        return jwt.encode({'iat': now, 'exp': now + 300}, self._secret, algorithm='HS256')

    async def load(self, query: dict[str, Any], fresh: bool = False) -> list[dict[str, Any]]:
        """The rows of one structured query (never SQL); `fresh` re-runs it rather than use Cube's cache.

        Waits while Cube answers "Continue wait", up to the timeout."""
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                res = await self._client.post(
                    f'{self._url}/load',
                    json={'query': query, **({'cache': 'must-revalidate'} if fresh else {})},
                    headers={'authorization': self._token()},
                    timeout=self._timeout_s,
                )
            except httpx.HTTPError as e:
                raise CubeError(f'Cube could not be reached: {e}') from e
            body: dict[str, Any] = res.json() if res.headers.get('content-type', '').startswith('application/json') else {}
            if body.get('error') == 'Continue wait' and time.monotonic() < deadline:
                await asyncio.sleep(self._wait_s)
                continue
            if res.status_code != 200 or 'error' in body:
                message = f'Cube answered {res.status_code}: {body.get("error", res.text[:200])}'
                raise (CubeNoData if _NO_TABLE.search(message) else CubeError)(message)
            data: list[dict[str, Any]] = body.get('data', [])
            return data

    async def cubes(self) -> list[dict[str, Any]]:
        """Cube's `/meta` as it answers, with the members that are not public left out."""
        try:
            res = await self._client.get(f'{self._url}/meta', headers={'authorization': self._token()}, timeout=self._timeout_s)
        except httpx.HTTPError as e:
            raise CubeError(f'Cube could not be reached: {e}') from e
        if res.status_code != 200:
            raise CubeError(f'Cube answered {res.status_code}: {res.text[:200]}')
        cubes: list[dict[str, Any]] = res.json().get('cubes', [])
        return [
            {**cube, **{k: [m for m in cube.get(k, []) if m.get('public', m.get('isVisible', True))] for k in ('measures', 'dimensions')}}
            for cube in cubes
        ]

    async def meta(self) -> list[dict[str, Any]]:
        """The governed members (public measures and dimensions of every cube): name, title, type, kind, description and the model's `meta`
        (Arabic words, synonyms, explanation: docs/context-spec.md section 4)."""
        members: list[dict[str, Any]] = []
        for cube in await self.cubes():
            if cube.get('type') == 'view':
                continue  # views carry words for agents (institution), not metrics
            for kind in ('measures', 'dimensions'):
                for m in cube.get(kind, []):
                    members.append(
                        {
                            'name': m['name'],
                            'title': m.get('shortTitle') or m.get('title') or m['name'],  # 'Headcount', not 'Enrollment Headcount'
                            'type': m.get('type'),
                            'agg_type': m.get('aggType'),
                            'kind': kind[:-1],
                            'description': m.get('description'),
                            'cube': cube.get('title') or cube['name'],
                            'meta': m.get('meta') or {},
                        }
                    )
        return members

    async def institution(self) -> dict[str, Any]:
        """The `institution` view's glossary and instructions (docs/context-spec.md section 4); empty when the model has none."""
        for cube in await self.cubes():
            if cube.get('name') == 'institution' and cube.get('type') == 'view':
                meta = cube.get('meta') or {}
                return {'glossary': list(meta.get('glossary') or []), 'instructions': list(meta.get('instructions') or [])}
        return {'glossary': [], 'instructions': []}
