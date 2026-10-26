"""A fake OpenAI-compatible server for tests: /v1/models and a streaming /v1/chat/completions that follows a tiny script. It speaks the real
wire protocol (server-sent chunks, tool calls, usage), so the real OpenAI client inside Pydantic AI runs against it over HTTP."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODELS = ['fake-chat', 'fake-no-tools']


def chunk(delta: dict[str, Any], finish: str | None = None, usage: dict[str, int] | None = None) -> str:
    body: dict[str, Any] = {'id': 'chatcmpl-1', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fake', 'choices': []}
    if usage is None:
        body['choices'] = [{'index': 0, 'delta': delta, 'finish_reason': finish}]
    else:
        body['usage'] = usage
    return f'data: {json.dumps(body)}\n\n'


def create_fake_openai() -> tuple[FastAPI, list[dict[str, Any]]]:
    app = FastAPI()
    requests: list[dict[str, Any]] = []

    @app.get('/v1/models')
    async def models() -> dict[str, Any]:
        return {'object': 'list', 'data': [{'id': m, 'object': 'model', 'owned_by': 'fake', 'max_model_len': 32768} for m in MODELS]}

    @app.post('/v1/chat/completions', response_model=None)
    async def completions(request: Request) -> Any:
        body = await request.json()
        requests.append({'auth': request.headers.get('authorization'), 'body': body})
        if body['model'] == 'fake-no-tools':
            return JSONResponse({'error': {'message': 'this model does not support tools'}}, status_code=400) if body.get('tools') else None
        messages = body['messages']
        tool_results = [m for m in messages if m['role'] == 'tool']
        tool_names = {t['function']['name'] for t in body.get('tools', [])}
        last_user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
        if isinstance(last_user, list):
            last_user = ' '.join(p.get('text', '') for p in last_user)

        async def stream() -> AsyncIterator[str]:
            usage = {'prompt_tokens': 50 + 10 * len(messages), 'completion_tokens': 20, 'total_tokens': 70 + 10 * len(messages)}
            if 'ping' in tool_names and not tool_results and 'ping tool' in last_user:
                yield chunk(
                    {
                        'role': 'assistant',
                        'tool_calls': [
                            {'index': 0, 'id': 'call_ping', 'type': 'function', 'function': {'name': 'ping', 'arguments': '{}'}}
                        ],
                    }
                )
                yield chunk({}, 'tool_calls')
            elif 'propose_chart' in tool_names and 'chart' in last_user and len(tool_results) < 2:
                # a short script that exercises the governed read and the chart draft: query, then propose, then answer
                query = {'measures': ['enrollment.headcount'], 'dimensions': ['enrollment.program']}
                name, args = (
                    ('query_metric', {'query': query})
                    if not tool_results
                    else (
                        'propose_chart',
                        {
                            'chart': {
                                'version': 1,
                                'title': 'Headcount by program',
                                'query': query,
                                'visual': {'type': 'bar', 'x': 'enrollment.program'},
                            }
                        },
                    )
                )
                yield chunk(
                    {
                        'role': 'assistant',
                        'tool_calls': [
                            {
                                'index': 0,
                                'id': f'call_{name}',
                                'type': 'function',
                                'function': {'name': name, 'arguments': json.dumps(args)},
                            }
                        ],
                    }
                )
                yield chunk({}, 'tool_calls')
            elif 'list_datasets' in tool_names and not tool_results:
                yield chunk(
                    {
                        'role': 'assistant',
                        'tool_calls': [
                            {'index': 0, 'id': 'call_1', 'type': 'function', 'function': {'name': 'list_datasets', 'arguments': ''}}
                        ],
                    }
                )
                yield chunk({'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]})
                yield chunk({}, 'tool_calls')
            else:
                text = (
                    'Here is the headcount by program, and a chart of it.'
                    if 'chart' in last_user and len(tool_results) >= 2
                    else 'Done.'
                    if tool_results and tool_results[-1]['content'] == 'pong'
                    else f'The warehouse has {json.loads(tool_results[-1]["content"])["datasets"][0]["dataset"]} data.'
                    if tool_results
                    else 'Hello from the fake model.'
                )
                for i in range(0, len(text), 8):
                    yield chunk({'role': 'assistant', 'content': text[i : i + 8]})
                    await asyncio.sleep(0)
                yield chunk({}, 'stop')
            yield chunk({}, usage=usage)
            yield 'data: [DONE]\n\n'

        return StreamingResponse(stream(), media_type='text/event-stream')

    return app, requests


class _QuietServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # not the main thread: signals belong to pytest
        pass


class ServerThread:
    """The fake server on a free local port, in a thread (so the tests' event loop and the server's do not share one)."""

    def __init__(self) -> None:
        self.app, self.requests = create_fake_openai()
        self.server = _QuietServer(uvicorn.Config(self.app, host='127.0.0.1', port=0, log_level='warning'))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = 0

    def start(self) -> str:
        self.thread.start()
        while not self.server.started:
            threading.Event().wait(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return f'http://127.0.0.1:{self.port}/v1'

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
