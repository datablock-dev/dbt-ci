"""Generic connector driving any dbt adapter through ``dbt run-operation``."""
from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.generic.run_operation import execute_statements, run_operation
from dbt_ci.connectors.generic.strategies import (
    generic_delete_strategy,
    generic_migration_strategy,
)

# No "client" or "methods" entries: this connector never talks to a warehouse SDK directly,
# it lets dbt's own adapter do it. Callers already treat both keys as optional.
generic_db_connector: ConnectorConfig = {
    "strategies": {
        "delete": generic_delete_strategy,
        "migration": generic_migration_strategy
    }
}

__all__ = [
    "execute_statements",
    "generic_db_connector",
    "run_operation",
]
