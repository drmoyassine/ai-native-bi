"""Stored messages as the chat shows them: the person's words, the assistant's text, and one item per tool call with its outcome, a table
for query_metric and a chart for propose_chart. Derived from the stored messages, so a reloaded conversation matches the live one."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from .turn import result_summary, short

SYSTEM_PREFIX = 'not run: '


def render_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    text = part.content if isinstance(part.content, str) else ' '.join(str(c) for c in part.content if isinstance(c, str))
                    items.append({'kind': 'user', 'text': text})
                elif isinstance(part, ToolReturnPart):
                    item = calls.get(part.tool_call_id)
                    if item is None:
                        continue
                    content = part.content
                    if isinstance(content, str) and content.startswith(SYSTEM_PREFIX):
                        item.update(ok=False, summary=content)
                        continue
                    item['ok'], item['summary'] = result_summary(part.tool_name, content)
                    if item['ok'] and isinstance(content, dict):
                        if part.tool_name == 'query_metric':
                            items.append(
                                {
                                    'kind': 'table',
                                    **{k: content.get(k) for k in ('rows', 'row_count', 'suppressed_cells', 'as_of', 'query')},
                                }
                            )
                        elif part.tool_name == 'propose_chart':
                            items.append({'kind': 'chart', 'draft_id': content.get('draft_id'), 'chart': content.get('chart')})
                elif isinstance(part, RetryPromptPart):
                    item = calls.get(part.tool_call_id or '')
                    if item is not None:
                        item.update(ok=False, summary=short(part.content))
        elif isinstance(message, ModelResponse):
            for out in message.parts:
                if isinstance(out, TextPart) and out.content.strip():
                    items.append({'kind': 'assistant', 'text': out.content})
                elif isinstance(out, ToolCallPart):
                    item = {'kind': 'tool', 'name': out.tool_name, 'args': short(out.args), 'ok': None, 'summary': None}
                    calls[out.tool_call_id] = item
                    items.append(item)
    return items
