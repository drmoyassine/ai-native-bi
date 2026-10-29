"""The setup agent (docs/setup-agent-spec.md, DEC-035) on the case that motivated it: an export whose column "Term" holds term codes,
which the name rules take for the term name. A scripted model stands in for the provider and records everything it is sent, so the
privacy rules (DEC-032) are checked on what actually leaves the BI."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from bi import accounts, mapping
from bi.connect import files, store
from bi.connect.files import Storage
from bi.connect.setup_agent import PartChoice, SetupProposal, process_setup, validate

from .conftest import PoolFactory, database_url
from .fakes import template_fields

FIELDS = template_fields()

DB = 'bi_setup_agent_test'
AS_OF = dt.date(2026, 10, 20)
HEADER = ['Student Number', 'Student Name', 'Student Email', 'Term', 'Start Date', 'Programme']
COLUMNS = [{'name': h, 'header': h} for h in HEADER]
KINDS = {
    'Student Number': 'identifier',
    'Student Name': 'personal',
    'Student Email': 'personal',
    'Term': 'category',
    'Start Date': 'date',
    'Programme': 'category',
}


def export(path: Path, n: int = 30, extra: str | None = None) -> Path:
    book = openpyxl.Workbook()
    ws = book.active
    assert ws is not None
    ws.append(['Example Polytechnic']), ws.append([])
    ws.append([*HEADER, extra] if extra else HEADER)
    for i in range(1, n + 1):
        ws.append(
            [
                f'2026{i:05d}',
                f'Secret Person {i}',
                f'secret{i}@example.edu',
                '202610',
                dt.date(2026, 8, 24),
                ['BSME', 'BSCE'][i % 2],
                *(['x'] if extra else []),
            ]
        )
    book.save(path)
    return path


GOOD = SetupProposal(
    parts=[
        PartChoice(part='student_id', column='Student Number', confidence='high', reason='A 9-digit identifier, one per student.'),
        PartChoice(part='term_code', column='Term', confidence='high', reason='Holds codes like 202610, not names.'),
        PartChoice(part='term_start', column='Start Date', confidence='high', reason='Dates.'),
        PartChoice(part='program', column='Programme', confidence='medium', reason='Program codes.'),
        PartChoice(part='level', column='Student Name', confidence='high', reason='?'),  # personal: dropped
        PartChoice(part='status', column='Nope', confidence='high', reason='?'),  # not a column: dropped
    ],
    header_row=None,
    column_notes={'Programme': 'program codes', 'Nope': 'ignored'},
)


class Recorder:
    """A scripted model that answers with `proposal` and keeps what it was sent."""

    def __init__(self, proposal: SetupProposal | Exception) -> None:
        self.proposal = proposal
        self.prompts: list[str] = []

    def model(self) -> Model:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for m in messages:
                if isinstance(m, ModelRequest):
                    self.prompts += [p.content for p in m.parts if isinstance(p, UserPromptPart) and isinstance(p.content, str)]
            if isinstance(self.proposal, Exception):
                raise self.proposal
            tool = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=self.proposal.model_dump_json())])

        return FunctionModel(respond)

    async def model_for(self, conv: dict[str, Any]) -> tuple[Model, dict[str, Any]]:
        return self.model(), {}


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool(DB)
    await accounts.create_user(p, 'admin@example.edu', 'Admin', 'a-long-password-0123', is_admin=True)
    return p


async def set_provider(pool: AsyncConnectionPool, *, samples: bool, build: bool = True, enabled: bool = True) -> None:
    async with pool.connection() as conn:
        await conn.execute('delete from model_provider')
        row = await (
            await conn.execute(
                """insert into model_provider (kind, name, base_url, enabled, may_see_samples)
                   values ('openai_compatible', 'Local', 'http://llm.local/v1', %s, %s) returning id""",
                [enabled, samples],
            )
        ).fetchone()
        assert row is not None
        await conn.execute(
            """insert into provider_model (provider_id, model_id, available, allowed_build, default_build)
               values (%s, 'setup-model', true, %s, %s)""",
            [row[0], build, build],
        )


async def waiting_sync(pool: AsyncConnectionPool, tmp_path: Path, name: str, by_admin: bool, same_layout: bool = False) -> str:
    """A sync of the problem export, waiting for review with the rules' proposal and the agent queued."""
    storage = Storage(f'file://{tmp_path}/files')
    source = await store.create_source(pool, name=name, type='file', dataset='enrollment', owner=None)
    async with pool.connection() as conn:
        admin = await (await conn.execute("select id::text from app_user where email = 'admin@example.edu'")).fetchone()
    assert admin is not None
    path = export(tmp_path / f'{name}.xlsx', extra=None if same_layout else f'Note {name}')  # each test has columns of its own
    with path.open('rb') as data:
        sync = await files.receive(
            pool, storage, source_id=source, user_id=admin[0] if by_admin else None, as_of=AS_OF, sheet=None, file_name=path.name, data=data
        )
    assert await files.process_sync(pool, storage, database_url(DB), sync, 5) == 'review'
    return sync


def test_validation_keeps_good_choices_drops_bad_ones_and_leaves_guesses_to_the_person() -> None:
    rules = {'student_id': 'Student Number', 'term_code': None, 'term': 'Term', 'term_start': 'Start Date'}
    checked = validate(GOOD, FIELDS, COLUMNS, KINDS, rules)
    assert checked.mapping['term_code'] == 'Term' and checked.mapping['program'] == 'Programme'  # the agent's correction stands
    assert checked.mapping.get('level') is None and checked.mapping.get('status') is None  # personal column and unknown column: dropped
    assert len(checked.dropped) == 2 and any('Nope' in d for d in checked.dropped)

    low = SetupProposal(parts=[PartChoice(part='term_code', column='Term', confidence='low', reason='a guess')])
    guessed = validate(low, FIELDS, COLUMNS, KINDS, rules)
    assert guessed.mapping['term_code'] is None and guessed.choices['term_code'].column == 'Term'  # shown, not applied

    twice = SetupProposal(
        parts=[
            PartChoice(part='term_code', column='Term', confidence='high', reason='codes'),
            PartChoice(part='program', column='Term', confidence='high', reason='?'),
            PartChoice(part='shoe', column='Term', confidence='high', reason='?'),
            PartChoice(part='term_code', column='Programme', confidence='high', reason='again'),
        ]
    )
    dup = validate(twice, FIELDS, COLUMNS, KINDS, {})
    assert dup.mapping['term_code'] == 'Term' and dup.mapping.get('program') is None and len(dup.dropped) == 3


async def test_the_rules_ask_the_agent_and_a_sample_is_masked_and_only_for_an_enabled_provider_and_an_admin(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await set_provider(pool, samples=True)
    sync = await waiting_sync(pool, tmp_path, 'Sampled', by_admin=True)
    row = await store.get_sync(pool, sync)
    assert row is not None and row['agent'] == {'state': 'queued', 'auto': True, 'by_admin': True}
    kept = await mapping.stored(pool, row['layout_id'], 'enrollment')
    assert (
        kept is not None and kept['proposed_by'] == 'rules' and kept['mapping']['term_code'] is None and kept['mapping']['term'] == 'Term'
    )

    model = Recorder(GOOD)
    assert await process_setup(pool, model.model_for, sync) == 'proposed'
    sent = '\n'.join(model.prompts)
    data = json.loads(model.prompts[0])
    assert 'sample_rows_masked' in data and 1 <= len(data['sample_rows_masked']) <= 20
    for secret in ('Secret Person', 'secret1@', 'example.edu', '202600001'):
        assert secret not in sent  # nothing identifying left the BI
    assert {r['Term'] for r in data['sample_rows_masked']} == {'202610'} and data['rows_above_the_header'] == ['Example Polytechnic']

    after = await mapping.stored(pool, row['layout_id'], 'enrollment')
    assert after is not None and after['status'] == 'proposed' and after['proposed_by'] == 'agent' and after['model'] == 'setup-model'
    assert after['mapping']['term_code'] == 'Term' and after['mapping']['program'] == 'Programme' and after['mapping']['level'] is None
    assert after['reasons']['term_code'] == {
        'column': 'Term',
        'confidence': 'high',
        'reason': 'Holds codes like 202610, not names.',
        'by': 'agent',
    }
    ended = await store.get_sync(pool, sync)
    assert ended is not None
    agent = ended['agent']
    assert agent['state'] == 'proposed' and agent['sample']['rows'] == len(data['sample_rows_masked']) and len(agent['dropped']) == 2
    assert agent['column_notes'] == {'Programme': 'program codes'}
    async with pool.connection() as conn:
        logged = await (
            await conn.execute('select purpose, rows, model_id, masked from sample_log where sync_id::text = %s', [sync])
        ).fetchall()
        runs = await (await conn.execute('select status from setup_run where sync_id::text = %s', [sync])).fetchall()
    assert len(logged) == 1 and logged[0][:3] == ('mapping proposal', len(data['sample_rows_masked']), 'setup-model')
    assert logged[0][3]['Student Email'] == 'replaced' and logged[0][3]['Term'] == 'as is' and runs == [('done',)]

    review = await files.review(pool, sync)
    assert review is not None and review['proposed_by'] == 'agent' and review['agent']['state'] == 'proposed'


async def test_no_sample_without_the_providers_switch_or_an_admin_and_the_agent_still_proposes(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await set_provider(pool, samples=False)
    sync = await waiting_sync(pool, tmp_path, 'Unsampled', by_admin=True)
    model = Recorder(GOOD)
    assert await process_setup(pool, model.model_for, sync) == 'proposed'
    assert 'sample_rows_masked' not in json.loads(model.prompts[0])  # the provider is not enabled for samples
    ended = await store.get_sync(pool, sync)
    assert ended is not None and ended['agent']['sample'] is None

    await set_provider(pool, samples=True)
    not_admin = await waiting_sync(pool, tmp_path, 'Not admin', by_admin=False)
    other = Recorder(GOOD)
    assert await process_setup(pool, other.model_for, not_admin) == 'proposed'
    assert 'sample_rows_masked' not in json.loads(other.prompts[0])  # not an admin's work
    async with pool.connection() as conn:
        count = await (await conn.execute('select count(*) from sample_log where sync_id::text = %s', [not_admin])).fetchone()
    assert count == (0,)


async def test_a_missing_model_a_spent_budget_a_failing_model_and_an_approved_layout_leave_the_rules_standing(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await set_provider(pool, samples=False, build=False)
    none = await waiting_sync(pool, tmp_path, 'No model', by_admin=True)
    assert await process_setup(pool, Recorder(GOOD).model_for, none) == 'none'
    ended = await store.get_sync(pool, none)
    assert ended is not None and 'Settings, Models' in ended['agent']['reason']

    await set_provider(pool, samples=False)
    spent = await waiting_sync(pool, tmp_path, 'Spent', by_admin=True)
    assert await process_setup(pool, Recorder(GOOD).model_for, spent, organization_cap=1, used_elsewhere=5) == 'none'
    ended = await store.get_sync(pool, spent)
    assert ended is not None and 'budget' in ended['agent']['reason']

    broken = await waiting_sync(pool, tmp_path, 'Broken', by_admin=True)
    assert await process_setup(pool, Recorder(RuntimeError('provider down')).model_for, broken) == 'failed'
    ended = await store.get_sync(pool, broken)
    assert ended is not None and "rules' proposal stands" in ended['agent']['error']
    kept = await mapping.stored(pool, ended['layout_id'], 'enrollment')
    assert kept is not None and kept['proposed_by'] == 'rules'  # untouched
    async with pool.connection() as conn:
        runs = await (await conn.execute('select status, error from setup_run where sync_id::text = %s', [broken])).fetchall()
    assert runs[0][0] == 'failed' and 'provider down' in runs[0][1]

    assert await process_setup(pool, Recorder(GOOD).model_for, broken) == 'skipped'  # already answered: not asked twice
    assert await process_setup(pool, Recorder(GOOD).model_for, '00000000-0000-0000-0000-000000000000') == 'skipped'


async def test_a_suggested_header_row_a_person_changing_a_choice_and_the_budget_counting_the_agents_tokens(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await set_provider(pool, samples=False)
    sync = await waiting_sync(pool, tmp_path, 'Header', by_admin=True)
    hint = GOOD.model_copy(update={'header_row': 1, 'header_reason': 'Row 1 looks like a title, not names.'})
    assert await process_setup(pool, Recorder(hint).model_for, sync) == 'proposed'
    ended = await store.get_sync(pool, sync)
    assert ended is not None and ended['agent']['header'] == {'row': 1, 'reason': 'Row 1 looks like a title, not names.'}

    me = await accounts.sign_in(pool, 'admin@example.edu', 'a-long-password-0123')
    assert me is not None
    row = ended
    review = await files.review(pool, sync)
    assert review is not None
    chosen = {**review['mapping'], 'program': None}  # the person drops the agent's program choice
    await files.approve(pool, sync, chosen, me[0].id, 'admin@example.edu')
    kept = await mapping.stored(pool, row['layout_id'], 'enrollment')
    assert (
        kept is not None
        and kept['status'] == 'approved'
        and kept['proposed_by'] == 'person'
        and kept['reasons']['term_code']['by'] == 'agent'
    )

    from bi.agent.routes import tokens_used

    assert await tokens_used(pool) > 0  # the setup agent's calls count against the organization's budget
    assert await tokens_used(pool, me[0].id) == 0  # and not against a person


async def test_the_worker_asks_the_agent_after_a_file_goes_to_review_and_the_agent_answers_in_its_own_job(
    pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """Through the real queue: the load job leaves the sync in review, defers the setup job, and the setup job proposes."""
    import httpx

    from bi.agent.turn import TurnDeps
    from bi.queue import AGENT_QUEUE, LOAD_QUEUE, AgentWorkerDeps, LoadDeps, create_queue, enqueue_load

    await set_provider(pool, samples=False)
    storage = Storage(f'file://{tmp_path}/files')
    source = await store.create_source(pool, name='Queued', type='file', dataset='enrollment', owner=None)
    path = export(tmp_path / 'queued.xlsx', extra='Note queued')
    with path.open('rb') as data:
        sync = await files.receive(pool, storage, source_id=source, user_id=None, as_of=AS_OF, sheet=None, file_name=path.name, data=data)
    recorder = Recorder(GOOD)
    turn = TurnDeps(pool=pool, cube=None, suppression_threshold=5, model_for=recorder.model_for)
    async with httpx.AsyncClient() as http:
        queue = create_queue(
            database_url(DB),
            load=LoadDeps(pool=pool, storage=storage, database_url=database_url(DB), suppression_threshold=5),
            agent=AgentWorkerDeps(turn=turn, secrets=None, http=http, organization_monthly_tokens=10_000_000),
        )
        async with queue.open_async():
            await enqueue_load(queue, sync)
            await queue.run_worker_async(queues=[LOAD_QUEUE, AGENT_QUEUE], wait=False, install_signal_handlers=False)
            await queue.run_worker_async(queues=[LOAD_QUEUE, AGENT_QUEUE], wait=False, install_signal_handlers=False)
    ended = await store.get_sync(pool, sync)
    assert ended is not None and ended['status'] == 'review' and ended['agent']['state'] == 'proposed'
    assert len(recorder.prompts) == 1 and ended['agent']['model'] == 'setup-model'
