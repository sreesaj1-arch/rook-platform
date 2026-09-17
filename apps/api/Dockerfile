FROM python:3.13.13-slim-bookworm AS builder

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

RUN python -m pip install --no-cache-dir uv==0.11.7
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
RUN python -c "import pathlib, platform; assert platform.python_version() == pathlib.Path('.python-version').read_text().strip()" \
    && uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.13.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 rook \
    && useradd --uid 10001 --gid rook --no-create-home --shell /usr/sbin/nologin rook
COPY --from=builder /app/.venv /app/.venv
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "rook_backend.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
