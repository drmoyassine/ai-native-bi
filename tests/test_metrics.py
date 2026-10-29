from __future__ import annotations

from typing import Any

import pytest

from bi.contract import CollectRequest
from bi.metrics import CubeMetricSource, cube_query, metrics_from_cubes
from bi.sources import CannotAnswer

COLUMNS: list[dict[str, Any]] = [
    {'key': 'program', 'label': 'Program', 'type': 'text', 'required': True},
    {'key': 'n', 'label': 'Headcount', 'type': 'integer'},
]


def request(query: dict[str, Any] | None = None, columns: list[dict[str, Any]] | None = COLUMNS, type: str = 'dataset') -> CollectRequest:
    return CollectRequest.model_validate(
        {
            'runId': 'run-1',
            'evidence': {'id': 'ev-1', 'title': 'Headcount', 'type': type, 'definition': None}
            | ({'columns': columns} if columns is not None else {}),
            'period': {'label': 'Fall 2026', 'start': '2026-08-24', 'end': '2026-12-18'},
            'query': query if query is not None else {'metric': 'enrollment_headcount', 'dimensions': ['program']},
            'callbackUrl': 'https://ams.example.org/api/bi/v0/runs/run-1/supply',
            'callbackToken': 't',
        }
    )


def member(name: str, **extra: Any) -> dict[str, Any]:
    return {'name': f'enrollment.{name}', 'public': True, **extra}


CUBES: list[dict[str, Any]] = [
    {
        'name': 'enrollment',
        'type': 'cube',
        'meta': {'steward': 'registrar', 'definition_version': 1, 'model': 'analytics.enrollment', 'ar': {'title': 'x'}},
        'measures': [member('headcount', meta={'metric': 'enrollment_headcount'}), member('as_of')],
        'dimensions': [member(d, type='string') for d in ('program', 'level', 'status', 'term_code', 'term_label')]
        + [member('term_start', type='time')],
    }
]
METRICS = metrics_from_cubes(CUBES)


class FakeCube:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data
        self.queries: list[dict[str, Any]] = []

    async def cubes(self) -> list[dict[str, Any]]:
        return CUBES

    async def load(self, query: dict[str, Any], fresh: bool = False) -> list[dict[str, Any]]:
        self.queries.append(query | {'fresh': fresh})
        return self.data


def source(data: list[dict[str, Any]]) -> tuple[CubeMetricSource, FakeCube]:
    cube = FakeCube(data)
    return CubeMetricSource(cube), cube  # type: ignore[arg-type]


def test_turns_a_request_into_a_governed_cube_query() -> None:
    req = request(
        {
            'metric': 'enrollment_headcount',
            'dimensions': ['program'],
            'filters': [{'field': 'level', 'op': 'eq', 'value': 'bachelor'}, {'field': 'program', 'op': 'in', 'value': ['BSME', 'BSCE']}],
        }
    )
    assert cube_query(METRICS['enrollment_headcount'], req) == {
        'measures': ['enrollment.headcount', 'enrollment.as_of'],
        'dimensions': ['enrollment.program'],
        'filters': [
            {'member': 'enrollment.level', 'operator': 'equals', 'values': ['bachelor']},
            {'member': 'enrollment.program', 'operator': 'equals', 'values': ['BSME', 'BSCE']},
        ],
        'timeDimensions': [{'dimension': 'enrollment.term_start', 'dateRange': ['2026-08-24', '2026-12-18']}],
    }


async def test_answers_rows_in_the_items_columns_with_the_earliest_as_of_and_lineage() -> None:
    src, cube = source(
        [
            {'enrollment.program': 'BSCE', 'enrollment.headcount': '87', 'enrollment.as_of': '20261025'},
            {'enrollment.program': 'BSME', 'enrollment.headcount': '120', 'enrollment.as_of': '20261020'},
        ]
    )
    supply = await src.answer(request())
    assert supply is not None
    assert supply.wire()['rows'] == [{'program': 'BSCE', 'n': 87}, {'program': 'BSME', 'n': 120}]
    assert supply.as_of == '2026-10-20'
    assert supply.lineage is not None and supply.lineage['metric'] == 'enrollment_headcount'
    assert supply.lineage['cube_query'] == cube_query(METRICS['enrollment_headcount'], request())
    assert cube.queries[0]['fresh'] is True


async def test_without_columns_the_value_goes_under_the_metric_name() -> None:
    src, _ = source([{'enrollment.headcount': '207', 'enrollment.as_of': '20261020'}])
    supply = await src.answer(request({'metric': 'enrollment_headcount'}, columns=None))
    assert supply is not None and supply.rows == [{'enrollment_headcount': 207}]


async def test_no_rows_or_only_an_empty_total_is_no_supply() -> None:
    assert await source([])[0].answer(request()) is None
    empty_total = [{'enrollment.headcount': '0', 'enrollment.as_of': None}]
    assert await source(empty_total)[0].answer(request({'metric': 'enrollment_headcount'}, columns=None)) is None


@pytest.mark.parametrize(
    ('query', 'columns', 'type', 'reason'),
    [
        ({'metric': 'enrollment_headcount', 'dimensions': ['gpa']}, None, 'dataset', 'no dimension gpa'),
        ({'metric': 'enrollment_headcount', 'filters': [{'field': 'gpa', 'op': 'gt', 'value': 3}]}, None, 'dataset', 'no filter'),
        ({'metric': 'enrollment_headcount', 'dimensions': ['program', 'level']}, COLUMNS, 'dataset', 'must be the dimensions'),
        ({'metric': 'enrollment_headcount'}, COLUMNS, 'dataset', 'must be the dimensions'),
        ({'metric': 'enrollment_headcount'}, None, 'document', 'not a document'),
    ],
)
async def test_says_why_it_cannot_answer_a_shape_it_does_not_have(
    query: dict[str, Any], columns: list[dict[str, Any]] | None, type: str, reason: str
) -> None:
    src, cube = source([{'enrollment.headcount': '1', 'enrollment.as_of': '20261020'}])
    with pytest.raises(CannotAnswer, match=reason):
        await src.answer(request(query, columns, type))
    assert cube.queries == []


async def test_answers_only_the_metrics_it_knows() -> None:
    src, _ = source([])
    assert await src.can_answer(request())
    assert not await src.can_answer(request({'metric': 'graduation_rate'}))


def test_the_model_decides_which_measures_the_ams_may_ask_for() -> None:
    assert set(METRICS) == {'enrollment_headcount'}
    m = METRICS['enrollment_headcount']
    assert (m.cube, m.measure, m.period, m.as_of) == ('enrollment', 'headcount', 'term_start', 'as_of')
    assert m.dimensions == {'program', 'level', 'status', 'term_code', 'term_label'}
    assert m.lineage == {'model': 'analytics.enrollment', 'steward': 'registrar', 'definition_version': 1}


def test_a_measure_without_a_declared_name_period_or_as_of_is_not_exposed() -> None:
    plain = [{**CUBES[0], 'measures': [member('headcount'), member('as_of')]}]
    assert metrics_from_cubes(plain) == {}
    two_times = [{**CUBES[0], 'dimensions': CUBES[0]['dimensions'] + [member('census', type='time')]}]
    assert metrics_from_cubes(two_times) == {}  # which time dimension the period applies to is not said
    chosen = [{**two_times[0], 'measures': [member('headcount', meta={'metric': 'h', 'period': 'census'}), member('as_of')]}]
    assert metrics_from_cubes(chosen)['h'].period == 'census'
    no_as_of = [{**CUBES[0], 'measures': [member('headcount', meta={'metric': 'h'})]}]
    assert metrics_from_cubes(no_as_of) == {}
