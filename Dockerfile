FROM ghcr.io/dbt-labs/dbt-core:1.11.3

RUN pip install dbt-duckdb

# Copy dbt project (or mount at runtime with -v)
COPY dbt /dbt
WORKDIR /dbt

# Install dbt dependencies
RUN dbt deps

# Set entrypoint to dbt command
ENTRYPOINT ["dbt"]

# Default to showing version
CMD ["--version"]