
FROM python:3.9 as builder

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="${PATH}:/root/.local/bin" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /maap-api-nasa

COPY pyproject.toml poetry.lock ./
RUN touch README.md

RUN poetry install --without dev && rm -rf $POETRY_CACHE_DIR

FROM python:3.9-slim as runtime

ENV VIRTUAL_ENV=/maap-api-nasa/.venv \
    PATH="/maap-api-nasa/.venv/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY api /maap-api-nasa/api
COPY api/settings.py /maap-api-nasa/api/settings.py
COPY logging.conf /maap-api-nasa/logging.conf
RUN mkdir /logs

