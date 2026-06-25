# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
WORKDIR /build

COPY requirements.lock pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install -r requirements.lock \
    && pip install --no-deps -e .

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    MOUS_DATA_ROOT=/data \
    MOUS_DERIVATIVES_ROOT=/derivatives \
    MOUS_REPO_ROOT=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libglib2.0-0 \
    libgl1 \
    libxrender1 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY reports ./reports

RUN pip install --no-deps -e . \
    && useradd --create-home --uid 1000 mous \
    && mkdir -p /data /derivatives /work \
    && chown -R mous:mous /app /data /derivatives /work

USER mous
WORKDIR /work

VOLUME ["/data", "/derivatives"]

ENTRYPOINT ["mous-pipeline"]
CMD ["--help"]
