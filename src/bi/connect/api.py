"""The REST API source (Connect data C2, docs/connect-data-spec.md § 4, § 5): one source per API, one stream per endpoint, read through
dlt's `rest_api` (pagination found by dlt, GET only). The settings are data a person fills in or the agent proposes (S5): a base URL,
the endpoints, the kind of authentication and a schedule. The credential lives in the secret store (DEC-020), never in the settings.

A sync reads one endpoint's items, flattens each into one row of text cells (nested objects as `parent__child`, lists as JSON), and hands
the table to the same path as a file: draft, profile, mapping, review, raw (bi.connect.files)."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from .sheets import Table

MAX_ROWS = 100_000
"""The most items one sync reads from an endpoint; more is a failure with that reason, not a silent cut."""

EndpointName = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_]{0,40}$')]


class ApiError(ValueError):
    """The API could not be read as configured (the reason says why)."""


class Endpoint(BaseModel):
    model_config = {'extra': 'forbid'}

    name: EndpointName
    path: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    """Relative to the base URL, such as `v1/items`."""
    data_selector: str | None = None
    """Where the items are in the response (a JSONPath such as `data` or `results.items`); dlt finds the list when it is left out."""
    params: dict[str, str | int | bool] = Field(default_factory=dict)

    @field_validator('path')
    @classmethod
    def _relative(cls, v: str) -> str:
        if '://' in v or v.startswith('//'):
            raise ValueError('an endpoint path is relative to the base URL')
        return v.lstrip('/')


class Auth(BaseModel):
    model_config = {'extra': 'forbid'}

    type: Literal['none', 'bearer', 'api_key', 'basic'] = 'none'
    header: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9-]{1,64}$')] = 'X-API-Key'
    """The header an API key is sent in."""
    username: str | None = None
    """For basic authentication; the password is the credential."""


class ApiSettings(BaseModel):
    model_config = {'extra': 'forbid'}

    base_url: str
    auth: Auth = Field(default_factory=Auth)
    endpoints: Annotated[list[Endpoint], Field(min_length=1, max_length=50)]
    schedule: Literal['manual', 'hourly', 'daily'] = 'manual'

    @field_validator('base_url')
    @classmethod
    def _https(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme not in ('https', 'http') or not parts.hostname:
            raise ValueError('the base URL must be an https address')
        if parts.scheme == 'http' and not _local(parts.hostname):
            raise ValueError('the base URL must use https (plain http only to this machine, for testing)')
        if parts.username or parts.password:
            raise ValueError('put the credential in its own field, not in the URL')
        return v if v.endswith('/') else v + '/'

    @model_validator(mode='after')
    def _unique(self) -> ApiSettings:
        names = [e.name for e in self.endpoints]
        if len(names) != len(set(names)):
            raise ValueError('two endpoints have the same name')
        if self.auth.type == 'basic' and not self.auth.username:
            raise ValueError('basic authentication needs a username')
        return self


def _local(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def rest_config(settings: ApiSettings, credential: str | None, endpoint: Endpoint) -> dict[str, Any]:
    """dlt's `rest_api` configuration for one endpoint (data, not code)."""
    auth: dict[str, Any] | None = None
    if settings.auth.type != 'none':
        if not credential:
            raise ApiError('the credential is not set')
        if settings.auth.type == 'bearer':
            auth = {'type': 'bearer', 'token': credential}
        elif settings.auth.type == 'api_key':
            auth = {'type': 'api_key', 'name': settings.auth.header, 'api_key': credential, 'location': 'header'}
        else:
            auth = {'type': 'http_basic', 'username': settings.auth.username, 'password': credential}
    resource: dict[str, Any] = {'path': endpoint.path, 'method': 'GET', 'params': dict(endpoint.params)}
    if endpoint.data_selector:
        resource['data_selector'] = endpoint.data_selector
    return {
        'client': {'base_url': settings.base_url, **({'auth': auth} if auth else {})},
        'resources': [{'name': endpoint.name, 'endpoint': resource}],
    }


def _flatten(item: Any, prefix: str = '') -> dict[str, str | None]:
    if not isinstance(item, dict):
        return {prefix or 'value': _text(item)}
    out: dict[str, str | None] = {}
    for key, value in item.items():
        name = f'{prefix}__{key}' if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        else:
            out[name] = _text(value)
    return out


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def read_stream(settings: ApiSettings, credential: str | None, endpoint_name: str) -> tuple[Table, str]:
    """Reads one endpoint's items as a table of text cells; returns it with a hash of its content (a repeat read loads nothing new)."""
    from dlt.sources.rest_api import rest_api_source

    endpoint = next((e for e in settings.endpoints if e.name == endpoint_name), None)
    if endpoint is None:
        raise ApiError(f'the source has no endpoint named "{endpoint_name}"')
    source = rest_api_source(rest_config(settings, credential, endpoint))  # type: ignore[arg-type]
    rows: list[dict[str, str | None]] = []
    try:
        for item in source.resources[endpoint.name]:
            rows.append(_flatten(item))
            if len(rows) > MAX_ROWS:
                raise ApiError(f'the endpoint returned more than {MAX_ROWS} items in one read')
    except ApiError:
        raise
    except Exception as e:  # the API's own error, said plainly (no credential is ever in it: dlt does not echo auth)
        raise ApiError(f'{endpoint.path} could not be read: {_reason(e)}') from e
    if not rows:
        raise ApiError(f'{endpoint.path} returned no items')
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    table = Table(
        where=endpoint.path,
        header_row=1,
        columns=columns,
        rows=[{c: row.get(c) for c in columns} for row in rows],
        row_numbers=list(range(1, len(rows) + 1)),
        guessed=False,
    )
    digest = hashlib.sha256(json.dumps(table.rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return table, digest


def _reason(e: BaseException) -> str:
    inner: BaseException = e
    while inner.__cause__ is not None:
        inner = inner.__cause__
    text = str(inner).split('\n')[0]
    return text[:300] or type(inner).__name__


def secret_handle(source_id: str) -> str:
    return f'secret://source.{source_id}.credential'
