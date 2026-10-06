# Minimal dbt image for the Docker runner e2e tests: dbt as the entrypoint, like the
# official dbt images. DBT_PACKAGES picks the dbt to install, e.g. "dbt==2.0.6" for
# dbt v2 (DuckDB is bundled) or "dbt-core==1.12.5 dbt-duckdb" for dbt v1.
FROM python:3.12-slim
ARG DBT_PACKAGES="dbt==2.0.6"
RUN pip install --no-cache-dir ${DBT_PACKAGES}
ENTRYPOINT ["dbt"]
