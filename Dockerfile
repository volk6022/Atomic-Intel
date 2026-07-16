FROM mcr.microsoft.com/playwright/python:v1.58.0

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN pip install uv && uv sync --frozen

RUN uv run playwright install --with-deps chromium

COPY src/ ./src/
COPY .env.example ./

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uv", "run", "python", "-m", "src.api.main"]