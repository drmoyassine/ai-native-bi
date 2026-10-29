"""Loads one file into a file source and rebuilds analytics, as an upload would:
`python -m bi.main_load FILE --source "Monthly export" --dataset DATASET --as-of 2026-10-20 [--sheet NAME]`.

An operator's path beside the Connect data page. Real exports hold personal data: they stay outside the repository (DEC-011).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from .config import load_env, storage
from .connect.files import load_now
from .log import log


async def run(args: argparse.Namespace) -> int:
    env = load_env()
    async with AsyncConnectionPool(env.DATABASE_URL, open=False) as pool:
        ended = await load_now(
            pool,
            storage(env),
            env.DATABASE_URL,
            args.file,
            source_name=args.source,
            dataset=args.dataset or None,
            as_of=args.as_of,
            sheet=args.sheet,
            threshold=env.SUPPRESSION_THRESHOLD,
        )
    log('info' if ended['status'] in ('loaded', 'review') else 'error', 'sync', status=ended['status'], rows=ended['rows'],
        tests=ended['tests'], note=ended['note'], error=ended['error'])  # fmt: skip
    return 0 if ended['status'] in ('loaded', 'review') else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m bi.main_load', description='Load a file into a file source and rebuild analytics.')
    parser.add_argument('file', type=Path)
    parser.add_argument('--source', required=True, help='the file source, made if it does not exist, e.g. "Monthly export"')
    parser.add_argument('--dataset', help='the dataset the source feeds, from an installed template (none: kept in raw only)')
    parser.add_argument('--as-of', required=True, type=dt.date.fromisoformat, help='the date the data is true as of (yyyy-mm-dd)')
    parser.add_argument('--sheet', help='the sheet to load (default: the first)')
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == '__main__':
    sys.exit(main())
