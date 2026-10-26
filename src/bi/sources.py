from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contract import CollectRequest, SupplyBody


class CannotAnswer(Exception):
    """The source knows the metric but not the request's shape (a dimension, a filter or the item's columns): no supply, and why."""


class Source(Protocol):
    """Where the BI finds the data for a request. Each source says which requests it can answer (usually by `query.metric` or the
    `endpoint` name) and answers with a supply, or None when it has no data for the period. A source NEVER invents values: no data
    means no supply (CLAUDE.md rule 3)."""

    name: str

    def can_answer(self, req: CollectRequest) -> bool: ...

    async def answer(self, req: CollectRequest) -> SupplyBody | None: ...


class SourceRegistry:
    def __init__(self, sources: Sequence[Source] = ()) -> None:
        self._sources = list(sources)

    def find(self, req: CollectRequest) -> Source | None:
        return next((s for s in self._sources if s.can_answer(req)), None)
