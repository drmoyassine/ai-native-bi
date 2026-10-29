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
from ..log import log
from . import files, store

# Every type the spec plans, in the order they are built (§ 11); only the available ones can be made.
TYPES: list[dict[str, Any]] = [
    {'type': 'file', 'label': 'File', 'hint': 'An export you upload: xlsx, xlsb, xls, ods or csv.', 'available': True},
    {'type': 'api', 'label': 'API', 'hint': 'A system with a web API, such as an LMS.', 'available': False, 'step': 'C2'},
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
            'datasets': [{'name': d, 'label': mapping.dataset_label(d)} for d in await mapping.installed_datasets(pool)],
        }

    @router.post('/sources', status_code=201)
    async def create(body: NewSource, user: Signed) -> dict[str, str]:
        if body.dataset is not None and body.dataset not in await mapping.installed_datasets(pool):
            raise HTTPException(422, f'unknown dataset "{body.dataset}"')
        try:
            id = await store.create_source(pool, name=body.name, type=body.type, dataset=body.dataset, owner=user.id)
        except store.SourceError as e:
            raise HTTPException(422, str(e)) from e
        log('info', 'source made', id=id, type=body.type, user=user.id)
        return {'id': id}

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
