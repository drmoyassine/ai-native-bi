"""The REST API source (Connect data C2): an API over real HTTP (a thread in the test), paged, behind a bearer token, read through dlt's
`rest_api` into the same draft, profile, mapping and review path as a file. The data is a second domain (DEC-037): a service desk."""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from bi import accounts, definitions
from bi.agent.secrets import DbSecretStore
from bi.connect import api, files, store
from bi.connect.files import Storage

from .conftest import PoolFactory, database_url

DB = 'bi_api_source_test'
TOKEN = 'desk-token-0123456789'
KEY = 'q' * 43  # a secret-store key of the right length (base64url of 32 bytes is 43 characters)
PASSWORD = 'a-long-password-0123'
TICKETS = [
    {'id': f'T-{n}', 'opened': f'2026-10-{n:02d}', 'queue': 'Network' if n % 2 else 'Access', 'owner': {'team': 'Ops'}, 'tags': ['x']}
    for n in range(1, 8)
]


class Desk(BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if self.headers.get('Authorization') != f'Bearer {TOKEN}':
            self.send_response(401)
            self.end_headers()
            return
        Desk.seen.append(parts.path)
        page = int(parse_qs(parts.query).get('page', ['1'])[0])
        items = TICKETS[(page - 1) * 3 : page * 3] if parts.path == '/v1/tickets' else []
        host = f'http://127.0.0.1:{self.server.server_address[1]}'  # type: ignore[index]
        more = page * 3 < len(TICKETS)
        body = {'data': items, 'next': f'{host}{parts.path}?page={page + 1}' if more else None}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope='module')
def desk() -> Iterator[str]:
    server = HTTPServer(('127.0.0.1', 0), Desk)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}/v1'
    server.shutdown()


@pytest.fixture(scope='module')
async def pool(make_pool: PoolFactory) -> AsyncConnectionPool:
    p = await make_pool(DB)
    await accounts.create_user(p, 'admin@example.org', 'Admin', PASSWORD, is_admin=True)
    await definitions.save_draft(p, 'subject', 'desk', {'label': {'en': 'Service desk'}}, None)
    await definitions.approve(p, 'subject', 'desk', None)
    ticket = {
        'subject': 'desk',
        'label': {'en': 'Ticket'},
        'grain': ['ticket_id'],
        'parts': [
            {'name': 'ticket_id', 'needed': True, 'expects': 'key', 'aliases': ['id']},
            {'name': 'opened_on', 'needed': True, 'expects': 'date', 'aliases': ['opened']},
            {'name': 'queue', 'normalize': 'lower'},
        ],
    }
    await definitions.save_draft(p, 'event', 'ticket', ticket, None)
    await definitions.approve(p, 'event', 'ticket', None)
    return p


def settings(base_url: str, **over: Any) -> dict[str, Any]:
    return {
        'base_url': base_url,
        'auth': {'type': 'bearer'},
        'endpoints': [{'name': 'tickets', 'path': 'tickets', 'data_selector': 'data'}, {'name': 'empty', 'path': 'nothing'}],
        **over,
    }


def test_the_settings_are_checked() -> None:
    with pytest.raises(ValueError, match='https'):
        api.ApiSettings.model_validate(settings('http://desk.example.org/v1'))
    with pytest.raises(ValueError, match='own field'):
        api.ApiSettings.model_validate(settings('https://user:pw@desk.example.org/'))
    with pytest.raises(ValueError, match='relative'):
        api.ApiSettings.model_validate(settings('https://desk.example.org/', endpoints=[{'name': 'a', 'path': 'https://evil.example/'}]))
    with pytest.raises(ValueError, match='same name'):
        api.ApiSettings.model_validate(settings('https://desk.example.org/', endpoints=[{'name': 'a', 'path': 'a'}] * 2))
    ok = api.ApiSettings.model_validate(settings('https://desk.example.org/v1'))
    assert ok.base_url == 'https://desk.example.org/v1/' and ok.schedule == 'manual'


def test_an_endpoint_is_read_page_by_page_and_flattened(desk: str) -> None:
    table, digest = api.read_stream(api.ApiSettings.model_validate(settings(desk)), TOKEN, 'tickets')
    assert len(table.rows) == len(TICKETS) and table.columns == ['id', 'opened', 'queue', 'owner__team', 'tags']
    assert table.rows[0] == {'id': 'T-1', 'opened': '2026-10-01', 'queue': 'Network', 'owner__team': 'Ops', 'tags': '["x"]'}
    assert api.read_stream(api.ApiSettings.model_validate(settings(desk)), TOKEN, 'tickets')[1] == digest  # same content, same hash
    with pytest.raises(api.ApiError, match='could not be read'):
        api.read_stream(api.ApiSettings.model_validate(settings(desk)), 'wrong', 'tickets')
    with pytest.raises(api.ApiError, match='no items'):
        api.read_stream(api.ApiSettings.model_validate(settings(desk)), TOKEN, 'empty')
    with pytest.raises(api.ApiError, match='credential is not set'):
        api.read_stream(api.ApiSettings.model_validate(settings(desk)), None, 'tickets')


async def test_an_api_source_is_connected_reviewed_and_loaded_like_a_file(pool: AsyncConnectionPool, desk: str, tmp_path: Path) -> None:
    from .test_app import APP, app_for

    secrets = DbSecretStore(pool, KEY)
    queued: list[str] = []

    async def enqueue(id: str) -> None:
        queued.append(id)

    async with app_for(pool, tmp_path, enqueue, secrets=secrets) as client:
        signed = await client.post('/app/api/session', json={'email': 'admin@example.org', 'password': PASSWORD}, headers=APP)
        assert signed.status_code == 200
        body = {'name': 'Desk API', 'type': 'api', 'settings': settings(desk), 'feeds': {'tickets': 'ticket'}}
        assert (await client.post('/app/api/sources', json=body, headers=APP)).status_code == 422  # bearer needs its token
        made = await client.post('/app/api/sources', json={**body, 'credential': TOKEN}, headers=APP)
        assert made.status_code == 201, made.text
        source_id = made.json()['id']
        found = (await client.get(f'/app/api/sources/{source_id}')).json()
        assert [s['name'] for s in found['streams']] == ['empty', 'tickets'] and TOKEN not in json.dumps(found)
        synced = await client.post(f'/app/api/sources/{source_id}/sync', headers=APP)
        assert synced.status_code == 202 and len(synced.json()['syncs']) == 2 and queued == synced.json()['syncs']
        again = await client.post(f'/app/api/sources/{source_id}/sync', headers=APP)
        assert again.json()['syncs'] == []  # each stream already has a sync waiting

    outcomes = {}
    for sync_id in queued:
        outcomes[sync_id] = await files.process_sync(pool, Storage(f'file://{tmp_path}/files'), database_url(DB), sync_id, 2, secrets)
    rows = {(await store.get_sync(pool, i) or {})['endpoint']: (await store.get_sync(pool, i) or {}) for i in queued}
    assert rows['empty']['status'] == 'failed' and 'no items' in rows['empty']['error']
    tickets = rows['tickets']
    assert tickets['status'] == 'review' and tickets['rows'] == len(TICKETS)  # the parts matched by alias: a person approves
    review = await files.review(pool, tickets['id'])
    assert review is not None and review['mapping'] == {'ticket_id': 'id', 'opened_on': 'opened', 'queue': 'queue'}
    admin = await accounts.sign_in(pool, 'admin@example.org', PASSWORD)
    assert admin is not None
    await files.approve(pool, tickets['id'], review['mapping'], admin[0].id, 'admin@example.org')
    assert await files.process_sync(pool, Storage(f'file://{tmp_path}/files'), database_url(DB), tickets['id'], 2, secrets) == 'loaded'
    with psycopg.connect(database_url(DB)) as conn:
        built = conn.execute('select ticket_id, opened_on, queue from analytics.ticket order by ticket_id').fetchall()
    assert built[0] == ('T-1', dt.date(2026, 10, 1), 'network') and len(built) == len(TICKETS)


async def test_a_scheduled_source_is_due_once_its_interval_has_passed(pool: AsyncConnectionPool, desk: str) -> None:
    source_id = await store.create_source(
        pool,
        name='Nightly desk',
        type='api',
        dataset=None,
        owner=None,
        settings=settings(desk, schedule='daily'),
        streams={'tickets': None},
    )
    assert source_id not in await store.due_api_sources(pool)  # a draft source is not scheduled
    async with pool.connection() as conn:
        await conn.execute("update source set state = 'live' where id::text = %s", [source_id])
    assert source_id in await store.due_api_sources(pool)
    assert len(await store.queue_endpoint_syncs(pool, source_id, None, dt.date.today())) == 1
    assert source_id not in await store.due_api_sources(pool)  # just synced
