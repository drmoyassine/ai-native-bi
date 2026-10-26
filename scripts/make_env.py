#!/usr/bin/env python3
"""Creates .env from .env.example with every secret and key filled with a strong random value: `python3 scripts/make_env.py`.

Run it on the server, before `docker compose up`. A value already set in .env is kept (run it again after pulling: it only adds
what is new and fills what is empty), and .env is written readable by its owner only. Secrets never go into .env.example, which is
committed. Standard library only, so it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

# The secrets this script makes up. Each is 32 random bytes, URL-safe (it also goes into database addresses).
GENERATED = ('POSTGRES_PASSWORD', 'BI_API_KEY', 'CUBE_API_SECRET', 'CUBE_DB_PASSWORD', 'BI_DB_PASSWORD', 'BI_SECRETS_KEY')
# Secrets that belong to someone else: never made up here.
FOREIGN = {'AMS_POSTGRES_PASSWORD': "the AMS's PostgreSQL superuser password (from the AMS's .env), for compose.together.yaml"}
PLACEHOLDERS = {'', 'change-me'}
LINE = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')


def read(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {m[1]: m[2] for line in path.read_text(encoding='utf-8').splitlines() if (m := LINE.match(line))}


def make(example: Path, target: Path) -> tuple[list[str], list[str]]:
    """Writes `target` from `example`; returns the keys it filled and the foreign secrets still empty."""
    current, defaults = read(target), read(example)
    filled: list[str] = []
    values: dict[str, str] = {}
    for key, default in defaults.items():
        value = current.get(key, default)
        if key in GENERATED and value in PLACEHOLDERS:
            value = secrets.token_urlsafe(32)
            filled.append(key)
        values[key] = value
    if 'DATABASE_URL' in values and ('POSTGRES_PASSWORD' in filled or values['DATABASE_URL'] in PLACEHOLDERS):
        values['DATABASE_URL'] = f'postgres://bi:{values["POSTGRES_PASSWORD"]}@postgres:5432/bi'
    lines = []
    for line in example.read_text(encoding='utf-8').splitlines():
        m = LINE.match(line)
        lines.append(f'{m[1]}={values[m[1]]}' if m else line)
    extra = {k: v for k, v in current.items() if k not in values}  # keys of the old .env the example no longer has: kept
    if extra:
        lines += ['', '# ---- Kept from the previous .env ----', *(f'{k}={v}' for k, v in extra.items())]
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(target, 0o600)
    return filled, [k for k in FOREIGN if values.get(k, '') in PLACEHOLDERS]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description='Create .env from .env.example with random secrets.')
    parser.add_argument('--example', type=Path, default=root / '.env.example')
    parser.add_argument('--out', type=Path, default=root / '.env')
    args = parser.parse_args()
    filled, missing = make(args.example, args.out)
    print(f'{args.out}: ' + (f'generated {", ".join(filled)}' if filled else 'every secret was already set'))
    if 'BI_API_KEY' in filled:
        print("  The AMS must send the same key: copy BI_API_KEY into the AMS's .env.")
    for key in missing:
        print(f'  Still to set by hand: {key}, {FOREIGN[key]}.')
    print("  Check AMS_CALLBACK_ORIGIN: the AMS's public address (co-deployment: http://app:3000).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
