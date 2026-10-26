"""The chart definition (DEC-012), version 1: what every chart is, whoever builds it (the agent, the API, the builder).

A definition is a Cube query (governed members only, structured, never SQL) plus the visual. It is checked here against Cube's
metadata; the browser turns it into ECharts options (web/src/chart.ts), never the agent or the API.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Member = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')]
Granularity = Literal['day', 'week', 'month', 'quarter', 'year']


class _Spec(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ChartFilter(_Spec):
    member: Member
    operator: Literal['equals', 'notEquals', 'gt', 'gte', 'lt', 'lte']
    values: Annotated[list[Annotated[str, StringConstraints(max_length=200)]], Field(min_length=1, max_length=50)]


class TimeRange(_Spec):
    dimension: Member
    date_range: tuple[dt.date, dt.date] | None = Field(default=None, alias='dateRange')
    granularity: Granularity | None = None

    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class ChartQuery(_Spec):
    measures: Annotated[list[Member], Field(min_length=1, max_length=5)]
    dimensions: Annotated[list[Member], Field(max_length=3)] = []
    filters: Annotated[list[ChartFilter], Field(max_length=10)] = []
    time: TimeRange | None = None


class Visual(_Spec):
    type: Literal['bar', 'line', 'pie', 'table', 'number']
    x: Member | None = None
    """The category or time axis: a dimension of the query (or its time dimension)."""
    series: Member | None = None
    """A second dimension that splits the measure into series (bar, line)."""


class ChartDefinition(_Spec):
    version: Literal[1] = 1
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    query: ChartQuery
    visual: Visual

    @model_validator(mode='after')
    def _visual_fits_the_query(self) -> ChartDefinition:
        q, v = self.query, self.visual
        axes = set(q.dimensions) | ({q.time.dimension} if q.time and q.time.granularity else set())
        if v.type == 'number' and (len(q.measures) != 1 or axes):
            raise ValueError('a number shows one measure, without dimensions')
        if v.type == 'pie' and (len(q.measures) != 1 or len(axes) != 1 or v.x not in axes):
            raise ValueError('a pie shows one measure by one dimension (x)')
        if v.type in ('bar', 'line') and (v.x is None or v.x not in axes):
            raise ValueError(f"a {v.type} chart needs x: one of the query's dimensions")
        if v.series is not None and (v.series not in axes or v.series == v.x or len(q.measures) != 1):
            raise ValueError('series is another dimension of the query, with one measure')
        return self


def unknown_members(chart: ChartDefinition, governed: list[dict[str, Any]]) -> list[str]:
    """The members the chart names that Cube does not offer (or offers as the other kind): only governed numbers are charted."""
    kinds = {m['name']: m['kind'] for m in governed}
    q = chart.query
    wanted = [(m, 'measure') for m in q.measures] + [(d, 'dimension') for d in q.dimensions]
    wanted += [(f.member, 'dimension') for f in q.filters] + ([(q.time.dimension, 'dimension')] if q.time else [])
    return sorted({m for m, kind in wanted if kinds.get(m) != kind})


def cube_query(chart: ChartDefinition) -> dict[str, Any]:
    q = chart.query
    out: dict[str, Any] = {
        'measures': q.measures,
        'dimensions': q.dimensions,
        'filters': [{'member': f.member, 'operator': f.operator, 'values': f.values} for f in q.filters],
        'limit': 5000,
    }
    if q.time:
        time: dict[str, Any] = {'dimension': q.time.dimension}
        if q.time.date_range:
            time['dateRange'] = [d.isoformat() for d in q.time.date_range]
        if q.time.granularity:
            time['granularity'] = q.time.granularity
        out['timeDimensions'] = [time]
    return out
