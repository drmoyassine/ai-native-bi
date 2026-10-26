"""Creates an account of the app: `python -m bi.main_user EMAIL --name NAME [--admin]`; the password is asked for (or read from
standard input when it is not a terminal). There are no default accounts: the first is made this way.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from psycopg_pool import AsyncConnectionPool

from .accounts import AccountError, create_user
from .config import load_env


async def _create(email: str, name: str, password: str, is_admin: bool) -> None:
    async with AsyncConnectionPool(load_env().DATABASE_URL, open=False) as pool:
        user = await create_user(pool, email, name, password, is_admin)
    print(f'created {user.email}' + (' (admin)' if user.is_admin else ''))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m bi.main_user', description='Create an account of the app.')
    parser.add_argument('email')
    parser.add_argument('--name', required=True)
    parser.add_argument('--admin', action='store_true')
    args = parser.parse_args(argv)
    password = getpass.getpass('Password: ') if sys.stdin.isatty() else sys.stdin.readline().rstrip('\n')
    try:
        asyncio.run(_create(args.email, args.name, password, args.admin))
    except AccountError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
