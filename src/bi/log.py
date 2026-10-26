from __future__ import annotations

import json
import sys
from typing import Any


def log(level: str, msg: str, **fields: Any) -> None:
    """One structured JSON log line on stdout (errors on stderr)."""
    line = json.dumps({'level': level, 'msg': msg, **fields}, default=str)
    print(line, file=sys.stderr if level == 'error' else sys.stdout, flush=True)
