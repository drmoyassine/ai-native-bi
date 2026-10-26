"""Loads one file and rebuilds analytics: `python -m bi.main_load FILE --dataset enrollment --as-of 2026-10-20 [--sheet NAME]`.

The operator's path until the frontend takes uploads (DEC-011). Real exports hold student data: they stay outside the repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import dbt
from .config import load_env
from .ingest import IngestError, load_file
from .log import log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m bi.main_load', description='Load a file into raw and rebuild analytics.')
    parser.add_argument('file', type=Path)
    parser.add_argument('--dataset', required=True, help='the raw table, e.g. enrollment')
    parser.add_argument('--as-of', required=True, type=dt.date.fromisoformat, help='the date the data is true as of (yyyy-mm-dd)')
    parser.add_argument('--sheet', help='the sheet to load (default: the first)')
    args = parser.parse_args(argv)
    env = load_env()
    options = {'client_kwargs': {'endpoint_url': env.S3_ENDPOINT_URL}} if env.S3_ENDPOINT_URL else None
    try:
        loaded = load_file(
            args.file,
            dataset=args.dataset,
            as_of=args.as_of,
            database_url=env.DATABASE_URL,
            files_url=env.RAW_FILES_URL,
            sheet=args.sheet,
            storage_options=options,
        )
        log(
            'info',
            'loaded',
            dataset=loaded.dataset,
            sha256=loaded.sha256,
            rows=loaded.rows,
            repeat=loaded.repeat,
            stored_at=loaded.stored_at,
        )
        built = dbt.build(env.DATABASE_URL)
        log('info', 'built', models=built.models, tests=built.tests)
    except (IngestError, dbt.TransformError) as e:
        log('error', 'load failed', error=str(e))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
