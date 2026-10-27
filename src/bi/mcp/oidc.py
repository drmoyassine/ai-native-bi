"""Tokens from an OpenID Connect issuer the BI trusts (docs/mcp-spec.md section 5; contract 6.2, the AMS as the BI's authorization
server). The BI checks every token itself against the issuer's published keys: no shared secret, no read of the issuer's data.

What a token must be to act for a person here: a JWT access token (`typ` at+jwt) signed with EdDSA by a key the issuer publishes,
from this issuer, for this audience (the MCP server's address), not expired, naming a person with an email and a BI role."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

ALGORITHMS = ['EdDSA']
"""Contract 6.2: the AMS signs with Ed25519. Anything else (and `none`) is refused."""
LEEWAY_SECONDS = 30
KEYS_TTL_SECONDS = 600
REFETCH_AFTER_SECONDS = 60
"""A token with a key id the issuer did not publish refetches the keys at most this often (key rotation, not an attacker's flood)."""


@dataclass
class OidcIssuer:
    issuer: str
    """As the issuer names itself (`iss`), e.g. https://ams.example.org/api/auth."""
    audience: str
    """This server's resource identifier, which tokens must name in `aud` (the MCP server's address)."""
    http: httpx.AsyncClient
    name: str = 'ams'
    _keys: dict[str, PyJWK] = field(default_factory=dict, repr=False)
    _fetched_at: float = field(default=0.0, repr=False)

    async def _load_keys(self) -> None:
        meta = await self.http.get(f'{self.issuer.rstrip("/")}/.well-known/openid-configuration', timeout=10)
        meta.raise_for_status()
        jwks_uri = meta.json()['jwks_uri']
        keys = await self.http.get(jwks_uri, timeout=10)
        keys.raise_for_status()
        loaded: dict[str, PyJWK] = {}
        for k in keys.json().get('keys', []):
            if k.get('kid') and k.get('use', 'sig') == 'sig':
                try:
                    loaded[k['kid']] = PyJWK(k)
                except jwt.PyJWKError:
                    continue  # a key of a type we do not use
        self._keys, self._fetched_at = loaded, time.monotonic()

    async def _key(self, kid: str) -> PyJWK | None:
        age = time.monotonic() - self._fetched_at
        if not self._keys or age > KEYS_TTL_SECONDS or (kid not in self._keys and age > REFETCH_AFTER_SECONDS):
            try:
                await self._load_keys()
            except (httpx.HTTPError, KeyError, ValueError):
                return self._keys.get(kid)  # the issuer is unreachable: keys already known still work
        return self._keys.get(kid)

    async def verify(self, token: str) -> dict[str, Any] | None:
        """The token's claims if it is a valid access token of this issuer for this audience; None otherwise."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            return None
        if header.get('alg') not in ALGORITHMS or str(header.get('typ', '')).lower() not in ('at+jwt', 'application/at+jwt'):
            return None  # an ID token (typ JWT, audience the client) is not an access token for the BI
        key = await self._key(str(header.get('kid', '')))
        if key is None:
            return None
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']},
            )
        except jwt.PyJWTError:
            return None
        return claims
