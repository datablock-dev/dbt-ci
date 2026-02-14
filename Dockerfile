FROM python:3.12-slim

# Build argument for dbt-core version
ARG DBT_CORE_VERSION=1.10.13

WORKDIR /app
COPY . /app

# Install dependencies excluding dbt-core, then install specific dbt-core version
RUN grep -v "^dbt-core" requirements.txt > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    pip install --no-cache-dir dbt-core==${DBT_CORE_VERSION} && \
    rm /tmp/requirements.txt

ENTRYPOINT ["python", "-m", "main"]