"""The AMS <-> BI contract v0 (docs/ams-bi-contract-v0.md), as Pydantic models.

A MIRROR of the AMS's packages/shared/src/collection.ts (BiCollectRequestSchema, BiSupplyBodySchema) and the pieces it uses
(DataColumnSchema, BiQuerySchema). The AMS owns the contract: change it there first, then here. Field names are the contract's
camelCase on the wire; tests/test_contract.py pins the example bodies of the contract document.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

EvidenceType = Literal['document', 'dataset']
ScheduleEvery = Literal['day', 'week', 'month', 'quarter', 'semester', 'year']
DataColumnType = Literal['text', 'number', 'integer', 'percent', 'date', 'choice', 'yes_no']

Name = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[a-z][a-z0-9_]{0,63}$')]
Trimmed = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise ValueError('must be an absolute URL')
    return value


Url = Annotated[str, AfterValidator(_url)]


class _Wire(BaseModel):
    """camelCase on the wire, snake_case in Python. Unknown keys are dropped (Zod's default)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class DataColumn(_Wire):
    key: Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_]*$')]
    label: Trimmed
    type: DataColumnType
    unit: Trimmed | None = None
    required: bool = False
    choices: list[Trimmed] | None = None
    help: Trimmed | None = None


ShortStr = Annotated[StrictStr, StringConstraints(max_length=200)]
FilterValue = ShortStr | StrictInt | StrictFloat | StrictBool | Annotated[list[ShortStr | StrictInt | StrictFloat], Field(max_length=100)]


class Filter(_Wire):
    field: Name
    op: Literal['eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte']
    value: FilterValue


class Evidence(_Wire):
    id: str
    title: str
    type: EvidenceType
    definition: str | None
    columns: list[DataColumn] | None = None


class Period(_Wire):
    label: str
    start: str
    end: str | None


class Query(_Wire):
    """The structured query, as data (never SQL)."""

    metric: Name | None = None
    dimensions: Annotated[list[Name], Field(max_length=20)] | None = None
    filters: Annotated[list[Filter], Field(max_length=20)] | None = None
    grain: ScheduleEvery | None = None


class CollectRequest(_Wire):
    """The body the AMS POSTs to the BI to ask for one period (contract 3.6)."""

    run_id: Annotated[str, StringConstraints(min_length=1)]
    endpoint: str | None = None
    """The endpoint name the item asked for; absent for the default path."""
    evidence: Evidence
    period: Period
    query: Query | None
    """Null when the item has none."""
    callback_url: Url
    callback_token: Annotated[str, StringConstraints(min_length=1)]


Cell = StrictStr | StrictInt | StrictFloat | StrictBool | None
_AS_OF = re.compile(r'^\d{4}-\d{2}-\d{2}([T ].*)?$')


class SupplyBody(_Wire):
    """What the BI sends back: in a 200 answer to the request, or in the callback (contract 4.2). Exactly one of rows, file_base64, url."""

    model_config = ConfigDict(extra='forbid')

    rows: Annotated[list[dict[str, Cell]], Field(max_length=50_000)] | None = None
    file_base64: Annotated[str, StringConstraints(min_length=1)] | None = None
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    mime: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    url: Url | None = None
    as_of: Annotated[str, StringConstraints(strip_whitespace=True, pattern=_AS_OF.pattern)]
    lineage: dict[str, Any] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] | None = None

    @model_validator(mode='after')
    def _one_content(self) -> SupplyBody:
        if (self.rows is not None) + (self.file_base64 is not None) + (self.url is not None) != 1:
            raise ValueError('send exactly one of rows, fileBase64 or url')
        if self.file_base64 is not None and self.file_name is None:
            raise ValueError('name the file (fileName)')
        if self.url is not None and not self.url.lower().startswith('https://'):
            raise ValueError('the address must be https (url)')
        return self

    def wire(self) -> dict[str, Any]:
        """The JSON body as sent: camelCase, with absent fields left out (the AMS refuses null for them); null cells in rows stay."""
        return {k: v for k, v in self.model_dump(mode='json').items() if v is not None}


class Issue(BaseModel):
    path: str
    message: str


class SupplyIssues(BaseModel):
    """The AMS's answer to a callback (contract 4.2): 200 supplied, 401 token, 409 not waiting, 422 does not fit (fix and resend)."""

    model_config = ConfigDict(extra='allow')

    issues: list[Issue] | None = None
