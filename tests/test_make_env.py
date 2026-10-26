from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'make_env.py'


def run(out: Path) -> str:
    done = subprocess.run(  # noqa: S603 (our own script)
        [sys.executable, str(SCRIPT), '--example', str(ROOT / '.env.example'), '--out', str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def values(path: Path) -> dict[str, str]:
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#') and '=' in line)


def test_fills_every_secret_once_and_keeps_what_is_set(tmp_path: Path) -> None:
    env = tmp_path / '.env'
    out = run(env)
    first = values(env)
    for key in ('POSTGRES_PASSWORD', 'BI_API_KEY', 'CUBE_API_SECRET', 'CUBE_DB_PASSWORD', 'BI_DB_PASSWORD'):
        assert len(first[key]) >= 43, key
    assert len({first[k] for k in ('POSTGRES_PASSWORD', 'BI_API_KEY', 'CUBE_API_SECRET', 'CUBE_DB_PASSWORD')}) == 4
    assert first['DATABASE_URL'] == f'postgres://bi:{first["POSTGRES_PASSWORD"]}@postgres:5432/bi'
    assert first['AMS_POSTGRES_PASSWORD'] == '' and 'AMS_POSTGRES_PASSWORD' in out
    assert env.stat().st_mode & 0o777 == 0o600

    env.write_text(env.read_text().replace(f'BI_API_KEY={first["BI_API_KEY"]}', 'BI_API_KEY=set-by-hand-0123456789') + 'MY_OWN=1\n')
    assert 'every secret was already set' in run(env)
    second = values(env)
    assert second['BI_API_KEY'] == 'set-by-hand-0123456789'
    assert second['CUBE_API_SECRET'] == first['CUBE_API_SECRET'] and second['MY_OWN'] == '1'
