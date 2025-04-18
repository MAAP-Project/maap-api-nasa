
FROM python:3.9 as builder

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    export PATH="/root/.local/bin:$PATH" 

ENV PATH="${PATH}:/root/.local/bin" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /maap-api-nasa

COPY pyproject.toml poetry.lock ./
RUN touch README.md

RUN poetry install --without dev --no-root && rm -rf $POETRY_CACHE_DIR

FROM python:3.9-slim as runtime

ENV VIRTUAL_ENV=/maap-api-nasa/.venv \
    PATH="/maap-api-nasa/.venv/bin:$PATH" \
    PYTHONPATH="/maap-api-nasa/.venv/lib:$PYTHONPATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3-psycopg2 \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

COPY api /maap-api-nasa/api
COPY logging.conf /maap-api-nasa/logging.conf

WORKDIR /maap-api-nasa

RUN mkdir /logs

