FROM ghcr.io/dbt-labs/dbt-core:1.11.3

COPY dbt /dbt

WORKDIR /dbt
RUN dbt deps

CMD ["--version"]