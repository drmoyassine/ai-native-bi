from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import ValidationError

from .contract import Issue, SupplyBody, SupplyIssues


@dataclass
class Supplied:
    status: Literal[200] = 200


@dataclass
class Ended:
    """401 (the token) or 409 (the run is not waiting): final, nothing to retry."""

    status: Literal[401, 409]


@dataclass
class Unfit:
    issues: list[Issue]
    status: Literal[422] = 422


@dataclass
class CallFailed:
    message: str


CallbackResult = Supplied | Ended | Unfit | CallFailed


async def post_supply(client: httpx.AsyncClient, url: str, token: str, body: SupplyBody, timeout_ms: int) -> CallbackResult:
    """Posts the supply to the AMS (contract 4.2) with the run's one-time token. Never follows a redirect."""
    try:
        res = await client.post(
            url,
            json=body.wire(),
            headers={'authorization': f'Bearer {token}'},
            follow_redirects=False,
            timeout=timeout_ms / 1000,
        )
    except httpx.HTTPError as e:
        return CallFailed(message=str(e) or type(e).__name__)
    if res.status_code == 200:
        return Supplied()
    if res.status_code in (401, 409):
        return Ended(status=401 if res.status_code == 401 else 409)
    if res.status_code == 422:
        try:
            parsed = SupplyIssues.model_validate_json(res.content)
        except ValidationError:
            return Unfit(issues=[])
        return Unfit(issues=parsed.issues or [])
    return CallFailed(message=f'the AMS answered {res.status_code}')
