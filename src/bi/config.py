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
    CUBE_API_URL: Annotated[str, StringConstraints(min_length=1)] | None = None
    """Cube's address (e.g. http://cube:4000); without it the worker has no source and every request ends no_source."""
    CUBE_API_SECRET: Annotated[str, StringConstraints(min_length=32)] | None = None
    """Cube's CUBEJS_API_SECRET, to sign the worker's tokens (HS256: at least 32 characters)."""
    CUBE_DB_USER: Annotated[str, StringConstraints(pattern=r'^[a-z_][a-z0-9_]{0,62}$')] = 'bi_cube'
    """The database role Cube connects as: it may read analytics only (TASK-007)."""
    CUBE_DB_PASSWORD: Annotated[str, StringConstraints(min_length=16)] | None = None
    """Its password. When set, the API creates the role at start (with BI_DATABASE_ADMIN_URL) and grants it analytics."""
    RAW_FILES_URL: Annotated[str, StringConstraints(min_length=1)] = 'file:///data/raw-files'
    """Where loaded files are kept unchanged: a folder (file://) or a bucket (s3://, with S3_ENDPOINT_URL for Garage)."""
    S3_ENDPOINT_URL: Annotated[str, StringConstraints(min_length=1)] | None = None


def load_env(source: Mapping[str, str] | None = None) -> Env:
    """Reads the environment; an empty value (as in a copied .env.example) means "not set"."""
    values = os.environ if source is None else source
    clean = {k: v for k, v in values.items() if k in Env.model_fields and v != ''}
    return Env.model_validate(clean)
