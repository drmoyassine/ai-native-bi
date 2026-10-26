# One image definition, two targets: `api` (the BI's HTTP surface) and `worker` (the collect jobs).
FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && useradd --system --uid 10001 bi
USER bi

FROM base AS api
EXPOSE 4000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=60s \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/healthz' % os.environ.get('PORT','4000'), timeout=2).status == 200 else 1)"
CMD ["python", "-m", "bi.main_api"]

FROM base AS worker
CMD ["python", "-m", "bi.main_worker"]
