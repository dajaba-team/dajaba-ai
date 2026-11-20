FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY src ./src
COPY contracts/display_labels_v1.json ./contracts/display_labels_v1.json
COPY corpus/manifest.json ./corpus/manifest.json
COPY migrations ./migrations
COPY alembic.ini ./
ARG SERVER_VERSION=dev
ENV SERVER_VERSION=${SERVER_VERSION} PYTHONPATH=/app/src
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn aml_ai.main:app --host 0.0.0.0 --port 8000"]
