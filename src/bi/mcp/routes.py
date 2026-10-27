"""The app's routes for personal access tokens (/app/api/tokens): a person makes, lists and revokes their own; an admin sees and
revokes everyone's. A token is shown once, when it is made."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, StringConstraints

from ..accounts import User
from . import principal


class NewToken(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    days: int = 90


def create_tokens_router(pool: AsyncConnectionPool, current_user: Callable[..., Awaitable[User]], public_url: str | None) -> APIRouter:
    router = APIRouter()
    Signed = Annotated[User, Depends(current_user)]

    @router.get('/tokens')
    async def list_tokens(user: Signed, everyone: bool = False) -> dict[str, Any]:
        if everyone and not user.is_admin:
            raise HTTPException(403, 'admins only')
        return {
            'tokens': await principal.list_tokens(pool, None if everyone else user.id),
            'mcp_url': f'{public_url}/mcp' if public_url else None,
            'expiry_days': list(principal.EXPIRY_DAYS),
        }

    @router.post('/tokens', status_code=201)
    async def create_token(body: NewToken, user: Signed) -> dict[str, Any]:
        try:
            record, token = await principal.create_token(pool, user.id, body.name, body.days)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {'token': token, 'record': record}

    @router.delete('/tokens/{token_id}', status_code=204)
    async def revoke(token_id: str, user: Signed) -> None:
        if not await principal.revoke_token(pool, token_id, user.id, user.is_admin):
            raise HTTPException(404, 'no such token')

    return router
