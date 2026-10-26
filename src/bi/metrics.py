"""The first source: KPIs read from Cube's governed layer (DEC-004) and answered to the AMS (contract 3.6, 4.2).

A request names a metric (`query.metric`), the dimensions to cut it by and filters; the period is the run's. The source turns that
into a Cube query (structured, never SQL), and the rows into the item's columns: each requested dimension under its own name and the
value under the one column that is not a dimension. A request it cannot shape is `CannotAnswer`; no rows is no supply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contract import CollectRequest, DataColumn, Filter, SupplyBody
from .cube import CubeClient
from .sources import CannotAnswer

_OPERATORS = {'eq': 'equals', 'ne': 'notEquals', 'in': 'equals', 'gt': 'gt', 'gte': 'gte', 'lt': 'lt', 'lte': 'lte'}


@dataclass(frozen=True)
class Metric:
    """A KPI as the AMS names it, and where it lives in Cube."""

    cube: str
    measure: str
    period: str
    """The time dimension the run's period applies to."""
    dimensions: frozenset[str]
    """The dimensions (and filter fields) the AMS may ask for."""
    as_of: str = 'as_of'
    """A measure holding the data's as-of date as yyyymmdd."""
    lineage: dict[str, Any] = field(default_factory=dict)

    def member(self, name: str) -> str:
        return f'{self.cube}.{name}'


METRICS: dict[str, Metric] = {
    'enrollment_headcount': Metric(
        cube='enrollment',
        measure='headcount',
        period='term_start',
        dimensions=frozenset({'program', 'level', 'status', 'term_code', 'term_label'}),
        lineage={'model': 'analytics.enrollment', 'steward': 'registrar', 'definition_version': 1},
    ),
}


def _filter(metric: Metric, f: Filter) -> dict[str, Any]:
    if f.field not in metric.dimensions:
        raise CannotAnswer(f'no filter on "{f.field}" (filters: {", ".join(sorted(metric.dimensions))})')
    values = f.value if isinstance(f.value, list) else [f.value]
    if f.op in ('gt', 'gte', 'lt', 'lte') and len(values) != 1:
        raise CannotAnswer(f'the filter on "{f.field}" compares with one value')
    return {
        'member': metric.member(f.field),
        'operator': _OPERATORS[f.op],
        'values': [str(v).lower() if isinstance(v, bool) else str(v) for v in values],
    }


def cube_query(metric: Metric, req: CollectRequest) -> dict[str, Any]:
    """The Cube query for a request: the measure and the as-of date, cut by the requested dimensions, filtered, within the period."""
    q = req.query
    dimensions = list(q.dimensions or []) if q else []
    unknown = [d for d in dimensions if d not in metric.dimensions]
    if unknown:
        raise CannotAnswer(f'no dimension {", ".join(unknown)} (dimensions: {", ".join(sorted(metric.dimensions))})')
    return {
        'measures': [metric.member(metric.measure), metric.member(metric.as_of)],
        'dimensions': [metric.member(d) for d in dimensions],
        'filters': [_filter(metric, f) for f in (q.filters or [])] if q else [],
        'timeDimensions': [
            {'dimension': metric.member(metric.period), 'dateRange': [req.period.start, req.period.end or req.period.start]}
        ],
    }


def value_column(dimensions: list[str], columns: list[DataColumn] | None, metric_name: str) -> str:
    """The key the value goes under: the one column that is not a dimension; the metric's name when the item has no columns."""
    if not columns:
        return metric_name
    keys = [c.key for c in columns]
    missing = [d for d in dimensions if d not in keys]
    rest = [k for k in keys if k not in dimensions]
    if missing or len(rest) != 1:
        raise CannotAnswer(
            f'the columns ({", ".join(keys)}) must be the dimensions ({", ".join(dimensions) or "none"}) and one column for the value'
        )
    return rest[0]


def _number(raw: Any, column: DataColumn | None) -> int | float | None:
    if raw is None:
        return None
    n = float(raw)
    if (column is None or column.type == 'integer') and n.is_integer():
        return int(n)
    return n


class CubeMetricSource:
    """Answers the metrics of METRICS from Cube."""

    name = 'cube'

    def __init__(self, cube: CubeClient, metrics: dict[str, Metric] = METRICS) -> None:
        self._cube = cube
        self._metrics = metrics

    def can_answer(self, req: CollectRequest) -> bool:
        return req.query is not None and req.query.metric in self._metrics

    async def answer(self, req: CollectRequest) -> SupplyBody | None:
        assert req.query is not None and req.query.metric is not None
        if req.evidence.type != 'dataset':
            raise CannotAnswer('a metric answers a dataset item, not a document')
        metric = self._metrics[req.query.metric]
        dimensions = list(req.query.dimensions or [])
        value_key = value_column(dimensions, req.evidence.columns, req.query.metric)
        column = next((c for c in req.evidence.columns or [] if c.key == value_key), None)
        query = cube_query(metric, req)
        data = await self._cube.load(query, fresh=True)  # an answer to the AMS reads the latest load, not Cube's cache
        dates = sorted(str(r[metric.member(metric.as_of)]) for r in data if r.get(metric.member(metric.as_of)) is not None)
        if not dates:
            return None  # no rows, or only Cube's empty total (a count of 0 over nothing): no data, no supply
        rows: list[dict[str, str | int | float | bool | None]] = [
            {**{d: r.get(metric.member(d)) for d in dimensions}, value_key: _number(r.get(metric.member(metric.measure)), column)}
            for r in data
        ]
        as_of = dates[0]  # the earliest: the whole answer is true at least as of then
        return SupplyBody(
            rows=rows,
            as_of=f'{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}',
            lineage={'source': 'cube', 'metric': req.query.metric, 'cube_query': query, **metric.lineage},
        )
