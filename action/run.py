"""Launch the dbt-ci GitHub Action; running this file puts dbt_ci_action on sys.path."""

import sys

from dbt_ci_action.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
