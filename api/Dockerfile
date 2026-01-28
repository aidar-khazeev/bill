FROM python:3.13.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/bill

COPY pyproject.toml uv.lock ./

# Не обновлять лок, не использовать кэш и не использовать dev зависимости
RUN uv sync --locked --no-cache --no-dev

COPY alembic.ini ./
COPY ./src .
COPY ./migrations ./migrations

RUN useradd fastapi

USER fastapi

EXPOSE 8000

CMD .venv/bin/alembic upgrade head && \
        .venv/bin/gunicorn main:app \
        --workers 4 \
        --worker-class uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:8000