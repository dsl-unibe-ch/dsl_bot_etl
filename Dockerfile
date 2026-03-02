FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv==0.8.14

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY scripts/ scripts/
COPY Makefile .

RUN uv run playwright install --with-deps chromium

ENV PYTHONPATH=/app

CMD ["make", "run-scheduled"]
