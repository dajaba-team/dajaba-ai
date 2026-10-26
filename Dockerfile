FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system -r pyproject.toml || uv pip install --system .
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
ARG SERVER_VERSION=dev
ENV SERVER_VERSION=${SERVER_VERSION} PYTHONPATH=/app/src
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn aml_ai.main:app --host 0.0.0.0 --port 8000"]
