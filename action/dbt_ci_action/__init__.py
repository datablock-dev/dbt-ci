"""Entrypoint package for the dbt-ci GitHub Action (see action.yml at the repository root).

It ships with the action rather than with the dbt-ci wheel, so it only uses the standard
library and has to run on whatever Python the runner provides.
"""
