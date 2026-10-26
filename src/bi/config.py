from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, StringConstraints


def origin_of(value: str) -> str:
    """scheme://host[:port] of an http(s) URL, lower-cased, default port left out (like a browser's URL.origin)."""
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('must be an http(s) URL')
    port = parts.port
    default = {'http': 80, 'https': 443}[parts.scheme]
    return f'{parts.scheme.lower()}://{parts.hostname}' + (f':{port}' if port and port != default else '')


class Env(BaseModel):
    PORT: Annotated[int, Field(gt=0)] = 4000
    DATABASE_URL: Annotated[str, StringConstraints(min_length=1)]
    BI_DATABASE_ADMIN_URL: Annotated[str, StringConstraints(min_length=1)] | None = None
    """A superuser address on the same server; when set, the BI creates its role and database (co-deployment, AMS DEC-034)."""
    BI_API_KEY: Annotated[str, StringConstraints(min_length=16)]
    """The key the AMS sends as a bearer credential (the AMS's BI_API_KEY); at least 16 characters."""
    AMS_CALLBACK_ORIGIN: Annotated[str, AfterValidator(origin_of)]
    """The only origin the BI calls back (the AMS's APP_PUBLIC_URL)."""
    CALLBACK_TIMEOUT_MS: Annotated[int, Field(gt=0)] = 30_000


def load_env(source: Mapping[str, str] | None = None) -> Env:
    """Reads the environment; an empty value (as in a copied .env.example) means "not set"."""
    values = os.environ if source is None else source
    clean = {k: v for k, v in values.items() if k in Env.model_fields and v != ''}
    return Env.model_validate(clean)
