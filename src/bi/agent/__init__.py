"""The agent (ROADMAP-003, docs/agent-spec.md): Pydantic AI in a worker job, the chat's events through PostgreSQL."""

import os

# Pydantic AI prints a start-up banner on its first agent; the BI's logs are JSON lines.
os.environ.setdefault('PYDANTIC_AI_NO_BANNER', '1')
