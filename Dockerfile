# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build: instala dependências com uv em camadas cacheáveis.
# ---------------------------------------------------------------------------
FROM python:3.15-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Primeiro só as dependências (cache de camadas enquanto o código muda).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Depois o projeto em si.
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Migrações e entrypoint usados em runtime.
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# ---------------------------------------------------------------------------
# Runtime: apenas o venv e o código, rodando como usuário não-root.
# ---------------------------------------------------------------------------
FROM python:3.15-slim AS runtime

RUN useradd --system --uid 10001 --create-home appuser \
    && mkdir -p /app \
    && chown appuser:appuser /app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /app/src
COPY --from=builder --chown=appuser:appuser /app/README.md /app/README.md
COPY --from=builder --chown=appuser:appuser /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=appuser:appuser /app/migrations /app/migrations
COPY --from=builder --chown=appuser:appuser /app/scripts /app/scripts

RUN chmod +x /app/scripts/entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

# O entrypoint aplica as migrações antes de subir o uvicorn.
CMD ["/app/scripts/entrypoint.sh"]
