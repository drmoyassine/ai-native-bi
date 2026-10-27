from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, SecretStr, StringConstraints

from .uploads import Storage


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
    APP_COOKIE_SECURE: bool = True
    """The session cookie is sent over HTTPS only. false only for a local http:// address."""
    WEB_DIR: Annotated[str, StringConstraints(min_length=1)] | None = None
    """The built web app to serve at / (the image sets it)."""
    BI_SECRETS_KEY: Annotated[str, StringConstraints(min_length=43, max_length=44)] | None = None
    """The key of the secret store (32 random bytes, base64url; scripts/make_env.py writes one). Without it: no provider keys."""
    AGENT_INSTITUTION_MONTHLY_TOKENS: Annotated[int, Field(gt=0)] = 100_000_000
    """The hard monthly cap of the institution (input plus output tokens of every turn)."""
    AGENT_PERSON_MONTHLY_TOKENS: Annotated[int, Field(gt=0)] = 10_000_000
    """The monthly share of each person."""
    SUPPRESSION_THRESHOLD: Annotated[int, Field(ge=1)] = 5
    """Counts under this are hidden from the agent (and, with TASK-008, from answers). The value comes from the privacy rules (TASK-002)."""
    PUBLIC_URL: Annotated[str, AfterValidator(origin_of)] | None = None
    """The app's own address (e.g. https://bi.example.edu): the MCP server's base URL and the only host its requests may name."""
    MCP_CALLS_PER_MINUTE: Annotated[int, Field(gt=0)] = 60
    """Calls of MCP tools a person may make in a minute (docs/mcp-spec.md section 7)."""
    MCP_CALLS_PER_DAY: Annotated[int, Field(gt=0)] = 2000
    ADMIN_EMAIL: Annotated[str, StringConstraints(min_length=3)] | None = None
    """With ADMIN_PASSWORD: the administrator the API creates at start if that email has no account yet (see admin_from_env)."""
    ADMIN_PASSWORD: SecretStr | None = None
    """Kept as a secret value: it never shows in a repr or a validation error. At least 12 characters (checked when the account is made)."""
    ADMIN_NAME: Annotated[str, StringConstraints(min_length=1)] = 'Administrator'


def load_env(source: Mapping[str, str] | None = None) -> Env:
    """Reads the environment; an empty value (as in a copied .env.example) means "not set"."""
    values = os.environ if source is None else source
    clean = {k: v for k, v in values.items() if k in Env.model_fields and v != ''}
    return Env.model_validate(clean)


def admin_from_env(env: Env) -> tuple[str, str, str] | None:
    """(email, password, name) of the administrator to make sure exists, or None when neither variable is set. Setting only one is a
    mistake worth stopping for: a half-set pair would otherwise leave an app nobody can sign in to."""
    if env.ADMIN_EMAIL is None and env.ADMIN_PASSWORD is None:
        return None
    if env.ADMIN_EMAIL is None or env.ADMIN_PASSWORD is None:
        raise ValueError('set ADMIN_EMAIL and ADMIN_PASSWORD together, or neither')
    return env.ADMIN_EMAIL, env.ADMIN_PASSWORD.get_secret_value(), env.ADMIN_NAME


def storage(env: Env) -> Storage:
    """Where files are kept (RAW_FILES_URL), with the bucket's endpoint when it is not AWS (S3_ENDPOINT_URL, e.g. Garage)."""
    options = {'client_kwargs': {'endpoint_url': env.S3_ENDPOINT_URL}} if env.S3_ENDPOINT_URL else None
    return Storage(files_url=env.RAW_FILES_URL, options=options)
