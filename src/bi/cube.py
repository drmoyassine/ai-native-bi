"""The BI's client for Cube's REST API: every read of a KPI goes through it (DEC-004, CLAUDE.md rule 5)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import jwt


class CubeError(RuntimeError):
    """Cube refused the query or could not be reached (the job is retried)."""


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
                raise CubeError(f'Cube answered {res.status_code}: {body.get("error", res.text[:200])}')
            data: list[dict[str, Any]] = body.get('data', [])
            return data

    async def meta(self) -> list[dict[str, Any]]:
        """The governed members (public measures and dimensions of every cube): name, title, type, kind and description."""
        try:
            res = await self._client.get(f'{self._url}/meta', headers={'authorization': self._token()}, timeout=self._timeout_s)
        except httpx.HTTPError as e:
            raise CubeError(f'Cube could not be reached: {e}') from e
        if res.status_code != 200:
            raise CubeError(f'Cube answered {res.status_code}: {res.text[:200]}')
        members: list[dict[str, Any]] = []
        for cube in res.json().get('cubes', []):
            for kind in ('measures', 'dimensions'):
                for m in cube.get(kind, []):
                    if m.get('public', m.get('isVisible', True)):
                        members.append(
                            {
                                'name': m['name'],
                                'title': m.get('shortTitle') or m.get('title') or m['name'],  # 'Headcount', not 'Enrollment Headcount'
                                'type': m.get('type'),
                                'kind': kind[:-1],
                                'description': m.get('description'),
                                'cube': cube.get('title') or cube['name'],
                            }
                        )
        return members
