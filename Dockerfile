FROM ghcr.io/dbt-labs/dbt-core:1.11.3

RUN pip install dbt-duckdb

# Set working directory
WORKDIR /usr/app

# Copy dbt project (or mount at runtime with -v)
COPY dbt /usr/app

# Install dbt dependencies
RUN dbt deps

# Set entrypoint to dbt command
ENTRYPOINT ["dbt"]

# Default to showing version
CMD ["--version"]