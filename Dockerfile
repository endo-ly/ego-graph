FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock /app/
COPY egograph/backend /app/egograph/backend
COPY egograph/pipelines /app/egograph/pipelines

RUN uv sync --all-packages --frozen

EXPOSE 8000

CMD ["uvicorn", "egograph.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
