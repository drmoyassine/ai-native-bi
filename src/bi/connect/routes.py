"""The Connect data API under /app/api (spec § 7): sources, files sent to a file source, and the review of what a sync found. A person
signed in makes sources and sends files; a BI admin approves (DEC-027: until there are stewards)."""

# No `from __future__ import annotations`: FastAPI must see the `Signed` alias defined inside the router function.
import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from .. import mapping
from ..accounts import User
from ..agent.secrets import SecretStore
from ..log import log
from . import api, files, store

# Every type the spec plans, in the order they are built (§ 11); only the available ones can be made.
TYPES: list[dict[str, Any]] = [
    {'type': 'file', 'label': 'File', 'hint': 'An export you upload: xlsx, xlsb, xls, ods or csv.', 'available': True},
    {'type': 'api', 'label': 'API', 'hint': 'A system with a web API: its endpoints are read on a schedule, read-only.', 'available': True},
    {'type': 'oracle', 'label': 'Oracle', 'hint': 'A database such as Banner, read-only.', 'available': False, 'step': 'C3'},
    {'type': 'postgres', 'label': 'PostgreSQL', 'hint': 'A PostgreSQL database, read-only.', 'available': False, 'step': 'C4'},
    {'type': 'mssql', 'label': 'SQL Server', 'hint': 'A SQL Server database, read-only.', 'available': False, 'step': 'C5'},
    {'type': 'mysql', 'label': 'MySQL', 'hint': 'A MySQL or MariaDB database, read-only.', 'available': False, 'step': 'C5'},
    {'type': 'folder', 'label': 'Folder', 'hint': 'Exports in Google Drive, S3, Azure, SFTP or a shared path.', 'available': False,
     'step': 'C5'},
    {'type': 'gsheets', 'label': 'Google Sheets', 'hint': 'A spreadsheet in Google Sheets.', 'available': False, 'step': 'C5'},
    {'type': 'inbox', 'label': 'Email', 'hint': 'Exports sent as attachments to a mailbox.', 'available': False, 'step': 'C5'},
    {'type': 'sharepoint', 'label': 'SharePoint', 'hint': 'Exports in SharePoint or OneDrive.', 'available': False, 'step': 'C5'},
]  # fmt: skip


class NewSource(BaseModel):
    name: str
    type: str
    dataset: str | None = None
    settings: dict[str, Any] | None = None
    """An API source's settings (bi.connect.api.ApiSettings)."""
    credential: str | None = None
    """An API source's token, key or password: kept in the secret store, never returned."""
    feeds: dict[str, str | None] | None = None
    """An API source's endpoints and the dataset each feeds (none: kept as raw data)."""


class Credential(BaseModel):
    credential: str


class Approval(BaseModel):
    mapping: dict[str, str | None] | None = None


class HeaderRow(BaseModel):
    row: int


def create_connect_router(
    pool: AsyncConnectionPool,
    storage: files.Storage,
    enqueue_load: Callable[[str], Awaitable[None]],
    enqueue_setup: Callable[[str], Awaitable[None]] | None,
    current_user: Callable[..., Awaitable[User]],
    secrets: SecretStore | None = None,
) -> APIRouter:
    router = APIRouter()
    Signed = Annotated[User, Depends(current_user)]

    def admin(user: User) -> None:
        if not user.is_admin:
            raise HTTPException(403, 'only a BI admin approves what is loaded')

    @router.get('/sources')
    async def sources(user: Signed) -> dict[str, Any]:
        return {
            'sources': await store.list_sources(pool),
            'types': TYPES,
            'datasets': [{'name': d, 'label': label} for d, label in (await mapping.dataset_labels(pool)).items()],
        }

    @router.post('/sources', status_code=201)
    async def create(body: NewSource, user: Signed) -> dict[str, str]:
        datasets = await mapping.installed_datasets(pool)
        if body.type == 'api':
            return await create_api(body, user, datasets)
        if body.dataset is not None and body.dataset not in datasets:
            raise HTTPException(422, f'unknown dataset "{body.dataset}"')
        try:
            id = await store.create_source(pool, name=body.name, type=body.type, dataset=body.dataset, owner=user.id)
        except store.SourceError as e:
            raise HTTPException(422, str(e)) from e
        log('info', 'source made', id=id, type=body.type, user=user.id)
        return {'id': id}

    async def create_api(body: NewSource, user: User, datasets: list[str]) -> dict[str, str]:
        if not user.is_admin:
            raise HTTPException(403, 'only a BI admin connects an API (its credential and what it reads)')
        try:
            settings = api.ApiSettings.model_validate(body.settings or {})
        except ValueError as e:
            raise HTTPException(422, f'the API settings are not valid: {e}') from e
        feeds = {e.name: (body.feeds or {}).get(e.name) for e in settings.endpoints}
        unknown = sorted({d for d in feeds.values() if d is not None and d not in datasets})
        if unknown:
            raise HTTPException(422, f'unknown dataset {", ".join(unknown)}')
        if settings.auth.type != 'none' and not body.credential:
            raise HTTPException(422, 'this authentication needs its credential')
        if body.credential and secrets is None:
            raise HTTPException(503, 'the secret store is not configured (BI_SECRETS_KEY), so a credential cannot be kept')
        try:
            id = await store.create_source(
                pool, name=body.name, type='api', dataset=None, owner=user.id, settings=settings.model_dump(), streams=feeds
            )
        except store.SourceError as e:
            raise HTTPException(422, str(e)) from e
        if body.credential and secrets is not None:
            await secrets.put(api.secret_handle(id), body.credential, user.id)
        log('info', 'source made', id=id, type='api', endpoints=len(feeds), user=user.id)  # never the credential
        return {'id': id}

    @router.put('/sources/{source_id}/credential', status_code=204)
    async def set_credential(source_id: str, body: Credential, user: Signed) -> None:
        admin(user)
        found = await store.get_source(pool, source_id)
        if found is None or found['type'] != 'api':
            raise HTTPException(404, 'no such API source')
        if secrets is None:
            raise HTTPException(503, 'the secret store is not configured (BI_SECRETS_KEY)')
        await secrets.put(api.secret_handle(source_id), body.credential, user.id)
        log('info', 'source credential replaced', id=source_id, user=user.id)

    @router.post('/sources/{source_id}/sync', status_code=202)
    async def sync_now(source_id: str, user: Signed) -> dict[str, Any]:
        """Reads every endpoint of an API source now (each a sync of its stream)."""
        admin(user)
        found = await store.get_source(pool, source_id)
        if found is None or found['type'] != 'api':
            raise HTTPException(404, 'no such API source')
        ids = await store.queue_endpoint_syncs(pool, source_id, user.id, dt.date.today())
        for id in ids:
            await enqueue_load(id)
        log('info', 'source sync queued', id=source_id, syncs=len(ids), user=user.id)
        return {'syncs': ids}

    @router.get('/sources/{source_id}')
    async def source(source_id: str, user: Signed) -> dict[str, Any]:
        found = await store.get_source(pool, source_id)
        if found is None:
            raise HTTPException(404, 'no such source')
        return found

    @router.post('/sources/{source_id}/files', status_code=202)
    async def send_file(
        source_id: str,
        user: Signed,
        file: Annotated[UploadFile, File()],
        as_of: Annotated[dt.date, Form(alias='asOf')],
        sheet: Annotated[str | None, Form()] = None,
    ) -> dict[str, str]:
        if as_of > dt.date.today():
            raise HTTPException(422, 'the as-of date is in the future')
        try:
            id = await files.receive(
                pool, storage, source_id=source_id, user_id=user.id, as_of=as_of, sheet=(sheet or '').strip() or None,
                file_name=file.filename or '', data=file.file,
            )  # fmt: skip
        except files.UploadError as e:
            raise HTTPException(422, str(e)) from e
        await enqueue_load(id)
        log('info', 'file received', sync=id, source=source_id, user=user.id)
        return {'id': id}

    @router.get('/syncs/{sync_id}/review')
    async def review(sync_id: str, user: Signed) -> dict[str, Any]:
        found = await files.review(pool, sync_id)
        if found is None:
            raise HTTPException(404, 'no such sync')
        return found

    @router.post('/syncs/{sync_id}/approve')
    async def approve(sync_id: str, body: Approval, user: Signed) -> dict[str, str]:
        admin(user)
        found = await store.get_sync(pool, sync_id)
        if found is None:
            raise HTTPException(404, 'no such sync')
        if found['status'] != 'review':
            raise HTTPException(409, 'only a sync waiting for review can be approved')
        try:
            await files.approve(pool, sync_id, body.mapping, user.id, user.email)
        except mapping.MappingError as e:
            raise HTTPException(422, str(e)) from e
        await enqueue_load(sync_id)
        log('info', 'sync approved', sync=sync_id, user=user.id)
        return {'status': 'queued'}

    @router.post('/syncs/{sync_id}/header')
    async def header(sync_id: str, body: HeaderRow, user: Signed) -> dict[str, str]:
        if not 1 <= body.row <= 1000:
            raise HTTPException(422, 'the header row is a row number from 1')
        if not await store.requeue(pool, sync_id, header_row=body.row, keep_header=False):
            raise HTTPException(409, 'this sync cannot be read again now')
        await enqueue_load(sync_id)
        return {'status': 'queued'}

    @router.post('/syncs/{sync_id}/ask-agent', status_code=202)
    async def ask_agent(sync_id: str, user: Signed) -> dict[str, str]:
        admin(user)  # the setup agent may be sent a masked sample, which only an admin's setup work does (DEC-032)
        found = await store.get_sync(pool, sync_id)
        if found is None:
            raise HTTPException(404, 'no such sync')
        if found['status'] != 'review' or not found['dataset']:
            raise HTTPException(409, 'the agent helps with a sync waiting for review that feeds a dataset')
        if enqueue_setup is None:
            raise HTTPException(503, 'the setup agent is not available')
        if (found['agent'] or {}).get('state') in ('queued', 'running'):
            raise HTTPException(409, 'the agent is already working on this')
        await store.update_sync(pool, sync_id, agent={'state': 'queued', 'auto': False, 'by_admin': True, 'requested_by': user.id})
        await enqueue_setup(sync_id)
        return {'status': 'queued'}

    @router.post('/syncs/{sync_id}/again')
    async def again(sync_id: str, user: Signed) -> dict[str, str]:
        if not await store.requeue(pool, sync_id):
            raise HTTPException(409, 'this sync cannot be loaded again now')
        await enqueue_load(sync_id)
        return {'status': 'queued'}

    return router
