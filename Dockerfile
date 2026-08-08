FROM python:3.12-slim

# Build argument for dbt-core version
ARG DBT_CORE_VERSION=1.10.13

WORKDIR /app
COPY . /app

# Dependencies come from pyproject.toml. This previously read a requirements.txt that
# was removed in 29e5667, so the build failed at this step. The [all] extra pulls in
# every optional connector, since an image cannot know which warehouse it will target.
# dbt-core is reinstalled afterwards to honour the pinned build argument.
RUN pip install --no-cache-dir ".[all]" && \
    pip install --no-cache-dir "dbt-core==${DBT_CORE_VERSION}"

ENTRYPOINT ["dbt-ci"]
CMD ["--help"]
