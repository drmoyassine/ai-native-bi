from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from bi.contract import CollectRequest, SupplyBody

# The example bodies of docs/ams-bi-contract-v0.md 3.6 and 4.2.
REQUEST: dict[str, Any] = {
    'runId': '0b6c5d2e-0000-4000-8000-000000000001',
    'endpoint': 'warehouse',
    'evidence': {
        'id': '0b6c5d2e-0000-4000-8000-000000000002',
        'title': 'Enrollment headcount',
        'type': 'dataset',
        'definition': 'Students enrolled per program',
        'columns': [
            {'key': 'program', 'label': 'Program', 'type': 'text', 'required': True},
            {'key': 'n', 'label': 'Headcount', 'type': 'integer', 'required': True},
        ],
    },
    'period': {'label': 'Fall 2026', 'start': '2026-08-24', 'end': '2026-12-18'},
    'query': {
        'metric': 'enrollment_headcount',
        'dimensions': ['program'],
        'filters': [{'field': 'level', 'op': 'eq', 'value': 'bachelor'}],
        'grain': 'semester',
    },
    'callbackUrl': 'https://ams.example.org/api/bi/v0/runs/0b6c5d2e-0000-4000-8000-000000000001/supply',
    'callbackToken': 'x' * 43,
}


def supply_ok(body: dict[str, Any]) -> bool:
    try:
        SupplyBody.model_validate(body)
    except ValidationError:
        return False
    return True


def test_reads_the_request_of_3_6() -> None:
    req = CollectRequest.model_validate(REQUEST)
    assert req.evidence.columns is not None and req.evidence.columns[1].type == 'integer'
    without = {k: v for k, v in REQUEST.items() if k != 'endpoint'} | {'query': None}
    assert CollectRequest.model_validate(without).query is None


def test_the_request_keeps_null_and_absent_apart() -> None:
    # `query` and `evidence.definition` may be null but must be present; `endpoint` may be absent.
    with pytest.raises(ValidationError):
        CollectRequest.model_validate({k: v for k, v in REQUEST.items() if k != 'query'})
    with pytest.raises(ValidationError):
        CollectRequest.model_validate({**REQUEST, 'query': {'metric': 'Enrollment'}})
    with pytest.raises(ValidationError):
        CollectRequest.model_validate({**REQUEST, 'query': {'filters': [{'field': 'level', 'op': 'eq', 'value': '1' * 201}]}})


def test_builds_the_supply_of_4_2_exactly_one_of_rows_a_file_or_an_https_address() -> None:
    assert supply_ok({'rows': [{'program': 'BSME', 'n': 120}], 'asOf': '2026-10-20', 'lineage': {'steward': 'registrar'}})
    assert not supply_ok({'asOf': '2026-10-20'})
    assert not supply_ok({'url': 'http://x.example.org/a.pdf', 'asOf': '2026-10-20'})
    assert not supply_ok({'fileBase64': 'AA==', 'asOf': '2026-10-20'})
    assert not supply_ok({'rows': [], 'asOf': '20 Oct'})
    assert not supply_ok({'rows': [], 'asOf': '2026-10-20', 'extra': 1})


def test_sends_the_supply_as_camel_case_without_absent_fields() -> None:
    body = SupplyBody(rows=[{'n': None}], as_of='2026-10-20', file_name=None)
    assert body.wire() == {'rows': [{'n': None}], 'asOf': '2026-10-20'}
    assert SupplyBody(rows=[{'n': 1}], as_of='2026-10-20').wire() == {'rows': [{'n': 1}], 'asOf': '2026-10-20'}
