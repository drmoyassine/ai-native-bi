"""Runs the dbt project in src/bi/transform (DEC-010) against the BI's database: raw -> staging -> analytics, with its tests."""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from importlib import resources
from typing import Any
from unittest import mock
from urllib.parse import unquote, urlsplit

from dbt.artifacts.schemas.run import RunExecutionResult
from dbt.cli.main import dbtRunner

_LOCK = threading.Lock()  # dbt keeps global state: one run at a time in a process


class TransformError(RuntimeError):
    """dbt failed: a model did not build or a data test did not pass (the message names them)."""


@dataclass
class Built:
    models: int
    tests: int


def _profile_env(database_url: str) -> dict[str, str]:
    u = urlsplit(database_url)
    return {
        'BI_DBT_HOST': u.hostname or 'localhost',
        'BI_DBT_PORT': str(u.port or 5432),
        'BI_DBT_USER': unquote(u.username or ''),
        'BI_DBT_PASSWORD': unquote(u.password or ''),
        'BI_DBT_DBNAME': u.path.lstrip('/'),
    }


def build(database_url: str, select: str | None = None) -> Built:
    """`dbt build` (models and their tests) in dependency order; raises TransformError when anything fails."""
    with _LOCK, resources.as_file(resources.files('bi') / 'transform') as project, tempfile.TemporaryDirectory() as work:
        args = ['build', '--project-dir', str(project), '--profiles-dir', str(project)]
        args += ['--target-path', f'{work}/target', '--log-path', f'{work}/logs', '--quiet']
        if select:
            args += ['--select', select]
        with mock.patch.dict(os.environ, _profile_env(database_url)):
            result = dbtRunner().invoke(args)
    if result.exception is not None:
        raise TransformError(f'dbt could not run: {result.exception}')
    nodes: list[Any] = list(result.result) if isinstance(result.result, RunExecutionResult) else []
    failed = [f'{r.node.name}: {r.message}' for r in nodes if str(r.status) in ('error', 'fail')]
    if failed or not result.success:
        raise TransformError('dbt build failed: ' + '; '.join(failed or ['see the dbt log']))
    return Built(
        models=sum(1 for r in nodes if r.node.resource_type == 'model'),
        tests=sum(1 for r in nodes if r.node.resource_type == 'test'),
    )
